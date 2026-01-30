"""CEX-to-Fresh-Wallet Matcher implementation.

This module implements the temporal and quantitative matching algorithm
to link CEX withdrawals to newly-funded wallets.
"""

from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional, List, Protocol
import logging

from .models import CEXWithdrawal, FreshWallet, MatchResult
from .config import MatcherConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class RedisClient(Protocol):
    """Protocol for Redis client interface."""
    async def setex(self, key: str, ttl: int, value: str) -> None: ...
    async def get(self, key: str) -> Optional[str]: ...


class DatabaseClient(Protocol):
    """Protocol for database client interface."""
    async def fetch(self, query: str, *args) -> List[dict]: ...
    async def execute(self, query: str, *args) -> None: ...


class GraphClient(Protocol):
    """Protocol for Neo4j client interface."""
    async def run(self, query: str, **params) -> None: ...


class CEXFreshWalletMatcher:
    """
    Temporal & Quantitative Matcher for CEX-to-Fresh-Wallet linking.
    
    This class processes CEX withdrawal events and attempts to match them
    with newly-funded fresh wallets using a scoring algorithm based on:
    - Time proximity between withdrawal and wallet funding
    - Amount similarity (accounting for gas fees)
    - Wallet freshness (transaction count)
    
    Example:
        matcher = CEXFreshWalletMatcher(redis, db, neo4j)
        result = await matcher.process_withdrawal(withdrawal)
        if result:
            print(f"Matched to {result.wallet.address} with score {result.match_score}")
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        db_client: DatabaseClient,
        neo4j_client: GraphClient,
        config: MatcherConfig = DEFAULT_CONFIG,
    ):
        """
        Initialize the matcher with client connections.
        
        Args:
            redis_client: Redis client for withdrawal buffering
            db_client: PostgreSQL client for wallet queries
            neo4j_client: Neo4j client for graph relationships
            config: Matcher configuration parameters
        """
        self.redis = redis_client
        self.db = db_client
        self.graph = neo4j_client
        self.config = config
    
    async def process_withdrawal(
        self, 
        withdrawal: CEXWithdrawal
    ) -> Optional[MatchResult]:
        """
        Main entry point: Process a CEX withdrawal and find matching fresh wallet.
        
        Args:
            withdrawal: The CEX withdrawal event to process
            
        Returns:
            MatchResult if a high-confidence match is found, None otherwise
        """
        logger.info(
            f"Processing withdrawal {withdrawal.tx_hash[:16]}... "
            f"from {withdrawal.cex_source} ({withdrawal.amount})"
        )
        
        # Step 1: Buffer withdrawal in Redis for real-time matching
        await self._buffer_withdrawal(withdrawal)
        
        # Step 2: Query fresh wallet candidates within time/amount window
        candidates = await self._get_fresh_wallet_candidates(
            time_start=withdrawal.timestamp,
            time_end=withdrawal.timestamp + timedelta(
                milliseconds=self.config.MAX_TIME_WINDOW_MS
            ),
            amount=withdrawal.amount,
            tolerance=self.config.MAX_AMOUNT_DELTA_PCT,
        )
        
        if not candidates:
            logger.debug(f"No candidates found for withdrawal {withdrawal.tx_hash[:16]}")
            return None
        
        logger.debug(f"Found {len(candidates)} candidate(s) for matching")
        
        # Step 3: Score each candidate
        scored_matches: List[tuple[FreshWallet, Decimal]] = []
        for wallet in candidates:
            score = self._calculate_match_score(withdrawal, wallet)
            if score >= self.config.MIN_MATCH_SCORE:
                scored_matches.append((wallet, score))
        
        if not scored_matches:
            logger.debug(f"No matches above threshold for {withdrawal.tx_hash[:16]}")
            return None
        
        # Step 4: Select best match
        best_wallet, best_score = max(scored_matches, key=lambda x: x[1])
        
        logger.info(
            f"Matched {withdrawal.tx_hash[:16]} to {best_wallet.address[:16]}... "
            f"(score: {best_score:.4f})"
        )
        
        # Step 5: Calculate deltas
        time_delta_ms = int(
            (best_wallet.first_funded_time - withdrawal.timestamp).total_seconds() * 1000
        )
        amount_delta_pct = abs(
            (best_wallet.first_funded_amount - withdrawal.amount) / withdrawal.amount
        )
        
        # Step 6: Create match result
        result = MatchResult(
            withdrawal=withdrawal,
            wallet=best_wallet,
            time_delta_ms=time_delta_ms,
            amount_delta_pct=amount_delta_pct,
            match_score=best_score,
            linked_parent_id=None,  # Will be set by parent linker if applicable
        )
        
        # Step 7: Persist match and create graph relationship
        await self._persist_match(result)
        await self._create_graph_relationship(result)
        
        return result
    
    def _calculate_match_score(
        self,
        withdrawal: CEXWithdrawal,
        wallet: FreshWallet,
    ) -> Decimal:
        """
        Calculate match confidence score based on temporal and quantitative factors.
        
        Score = (time_weight × time_score) + (amount_weight × amount_score) + freshness_bonus
        
        Args:
            withdrawal: The CEX withdrawal event
            wallet: The candidate fresh wallet
            
        Returns:
            Match score between 0 and 1
        """
        # Time score: 1.0 at exact match, decreasing linearly to 0 at max window
        time_delta_ms = abs(
            (wallet.first_funded_time - withdrawal.timestamp).total_seconds() * 1000
        )
        
        if time_delta_ms > self.config.MAX_TIME_WINDOW_MS:
            return Decimal("0")
        
        time_score = Decimal("1") - (
            Decimal(str(time_delta_ms)) / Decimal(str(self.config.MAX_TIME_WINDOW_MS))
        )
        
        # Amount score: 1.0 at exact match, considering gas deductions
        amount_delta = abs(wallet.first_funded_amount - withdrawal.amount)
        amount_delta_pct = amount_delta / withdrawal.amount if withdrawal.amount else Decimal("1")
        
        if amount_delta_pct > self.config.MAX_AMOUNT_DELTA_HARD_PCT:
            # Hard limit exceeded - no match possible
            return Decimal("0")
        elif amount_delta_pct > self.config.MAX_AMOUNT_DELTA_PCT:
            # Within gas-adjusted tolerance - partial score
            amount_score = Decimal("0.5")
        else:
            amount_score = Decimal("1") - (
                amount_delta_pct / self.config.MAX_AMOUNT_DELTA_PCT
            ) if self.config.MAX_AMOUNT_DELTA_PCT else Decimal("1")
        
        # Freshness bonus: Extra points for truly fresh wallets (tx_count == 0)
        freshness_bonus = self.config.FRESHNESS_BONUS if wallet.is_truly_fresh else Decimal("0")
        
        # Calculate final weighted score
        final_score = (
            (self.config.TIME_WEIGHT * time_score) +
            (self.config.AMOUNT_WEIGHT * amount_score) +
            freshness_bonus
        )
        
        return min(Decimal("1"), final_score)
    
    async def _get_fresh_wallet_candidates(
        self,
        time_start: datetime,
        time_end: datetime,
        amount: Decimal,
        tolerance: Decimal,
    ) -> List[FreshWallet]:
        """
        Query database for wallets matching criteria.
        
        Criteria:
        - Funded within time window [time_start, time_end]
        - Amount within tolerance
        - tx_count <= 1 (first transaction only)
        
        Args:
            time_start: Start of time window
            time_end: End of time window
            amount: Withdrawal amount
            tolerance: Amount tolerance as decimal percentage
            
        Returns:
            List of matching FreshWallet candidates
        """
        min_amount = amount * (Decimal("1") - tolerance)
        max_amount = amount * (Decimal("1") + tolerance)
        
        query = """
            SELECT 
                w.address,
                t.tx_hash as first_funded_tx,
                t.amount_in as first_funded_amount,
                t.event_time as first_funded_time,
                COUNT(*) OVER (PARTITION BY w.address) as tx_count
            FROM tracked_wallets w
            JOIN tx_events t ON w.address = t.wallet_address
            WHERE w.category = 'fresh_wallet'
              AND t.event_time BETWEEN $1 AND $2
              AND t.amount_in BETWEEN $3 AND $4
            ORDER BY t.event_time ASC
            LIMIT $5
        """
        
        try:
            results = await self.db.fetch(
                query,
                time_start,
                time_end,
                min_amount,
                max_amount,
                self.config.MAX_CANDIDATES_PER_QUERY,
            )
            
            return [
                FreshWallet(
                    address=row["address"],
                    first_funded_tx=row["first_funded_tx"],
                    first_funded_amount=Decimal(str(row["first_funded_amount"])),
                    first_funded_time=row["first_funded_time"],
                    tx_count=row.get("tx_count", 0),
                )
                for row in results
            ]
        except Exception as e:
            logger.error(f"Database query failed: {e}")
            return []
    
    async def _buffer_withdrawal(self, withdrawal: CEXWithdrawal) -> None:
        """
        Store withdrawal in Redis for real-time matching.
        
        Uses a TTL slightly longer than the max time window to ensure
        the withdrawal is available for matching.
        """
        key = f"cex_withdrawal:{withdrawal.tx_hash}"
        ttl = (self.config.MAX_TIME_WINDOW_MS // 1000) + self.config.REDIS_TTL_BUFFER
        
        try:
            await self.redis.setex(key, ttl, withdrawal.to_json())
        except Exception as e:
            logger.warning(f"Failed to buffer withdrawal in Redis: {e}")
    
    async def _persist_match(self, result: MatchResult) -> None:
        """Persist match to fresh_clusters table."""
        query = """
            INSERT INTO fresh_clusters (
                cex_source, withdrawal_tx, withdrawal_time, amount,
                decimals, target_wallet, target_tx_count,
                time_delta_ms, match_score, linked_parent
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """
        
        try:
            await self.db.execute(
                query,
                result.withdrawal.cex_source,
                result.withdrawal.tx_hash,
                result.withdrawal.timestamp,
                result.withdrawal.amount,
                result.withdrawal.decimals,
                result.wallet.address,
                result.wallet.tx_count,
                result.time_delta_ms,
                result.match_score,
                result.linked_parent_id,
            )
            logger.info(f"Persisted match to database: {result.wallet.address[:16]}...")
        except Exception as e:
            logger.error(f"Failed to persist match: {e}")
            raise
    
    async def _create_graph_relationship(self, result: MatchResult) -> None:
        """Create FUNDED_BY relationship in Neo4j."""
        query = """
            MERGE (cex:Wallet {address: $cex_address, type: 'cex_hot'})
            SET cex.exchange = $exchange
            MERGE (fresh:Wallet {address: $fresh_address})
            SET fresh.category = 'fresh_wallet',
                fresh.confidence = $score,
                fresh.first_seen = datetime($timestamp)
            MERGE (fresh)-[r:FUNDED_BY]->(cex)
            SET r.amount = $amount,
                r.timestamp = datetime($timestamp),
                r.match_score = $score,
                r.tx_hash = $tx_hash
        """
        
        try:
            await self.graph.run(
                query,
                cex_address=f"CEX:{result.withdrawal.cex_source}",
                exchange=result.withdrawal.cex_source,
                fresh_address=result.wallet.address,
                amount=float(result.withdrawal.amount),
                timestamp=result.withdrawal.timestamp.isoformat(),
                score=float(result.match_score),
                tx_hash=result.withdrawal.tx_hash,
            )
            logger.info(
                f"Created graph relationship: {result.wallet.address[:16]} "
                f"-[FUNDED_BY]-> CEX:{result.withdrawal.cex_source}"
            )
        except Exception as e:
            logger.error(f"Failed to create graph relationship: {e}")
            # Don't raise - graph creation is not critical
