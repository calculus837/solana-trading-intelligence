"""Cabal Correlation Engine - Detects coordinated wallet behavior."""

from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Set, Tuple, Protocol
from collections import defaultdict
import logging
import uuid

from .models import CorrelationEvent, WalletCluster, CorrelationResult
from .config import CorrelationConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class DatabaseClient(Protocol):
    """Protocol for database client interface."""
    async def fetch(self, query: str, *args) -> List[dict]: ...
    async def execute(self, query: str, *args) -> None: ...


class GraphClient(Protocol):
    """Protocol for Neo4j client interface."""
    async def run(self, query: str, **params) -> List[dict]: ...


class CabalCorrelationEngine:
    """
    Detects coordinated wallet behavior indicating potential cabals.
    
    The engine monitors contract interactions and identifies wallets that:
    1. Interact with the same contracts within a short time window
    2. Show consistent transaction ordering patterns
    3. Have high historical co-occurrence frequency
    
    When correlated wallets are detected, the engine:
    - Creates/updates wallet clusters in Neo4j
    - Escalates confidence scores for involved wallets
    - Emits alerts for high-correlation events
    
    Algorithm (from implementation plan):
    ```
    FOR each new contract interaction event E:
      1. Check if contract C is in "monitored" set
      2. Query: Which wallets interacted with C within BLOCK_WINDOW?
      3. IF count(matching_wallets) >= THRESHOLD:
         a. Create/Update cluster relationship in Neo4j
         b. Calculate correlation_score
         c. Escalate confidence for all involved wallets
      4. Update graph edges with new weights
    ```
    """
    
    def __init__(
        self,
        db_client: DatabaseClient,
        neo4j_client: GraphClient,
        config: CorrelationConfig = DEFAULT_CONFIG,
    ):
        """
        Initialize the correlation engine.
        
        Args:
            db_client: PostgreSQL client for event queries
            neo4j_client: Neo4j client for graph operations
            config: Correlation configuration parameters
        """
        self.db = db_client
        self.graph = neo4j_client
        self.config = config
        
        # In-memory cache for recent events (slot -> events)
        self._event_cache: Dict[int, List[CorrelationEvent]] = defaultdict(list)
        self._cache_max_slots = 100  # Keep last 100 slots
        
        # Cluster cache
        self._clusters: Dict[str, WalletCluster] = {}
        
        # Wallet to cluster mapping
        self._wallet_clusters: Dict[str, str] = {}
    
    async def process_event(
        self, 
        event: CorrelationEvent
    ) -> List[CorrelationResult]:
        """
        Process a contract interaction event and detect correlations.
        
        Args:
            event: The contract interaction event
            
        Returns:
            List of CorrelationResult for any detected correlations
        """
        # Check if contract is in monitored set
        if event.contract_address not in self.config.MONITORED_PROGRAMS:
            return []
        
        logger.debug(
            f"Processing event: {event.wallet_address[:16]}... "
            f"-> {event.contract_address[:16]}... (slot {event.slot})"
        )
        
        # Cache the event
        self._cache_event(event)
        
        # Query for other wallets that interacted with this contract recently
        matching_wallets = await self._find_correlated_wallets(event)
        
        if len(matching_wallets) < self.config.MIN_CLUSTER_SIZE:
            return []
        
        logger.info(
            f"Potential cabal detected: {len(matching_wallets)} wallets "
            f"on {event.contract_address[:16]}..."
        )
        
        # Calculate pairwise correlations
        results = []
        for other_event in matching_wallets:
            if other_event.wallet_address == event.wallet_address:
                continue
            
            correlation = await self._calculate_correlation(event, other_event)
            
            if correlation.correlation_score >= self.config.MIN_CORRELATION_SCORE:
                results.append(correlation)
                
                # Update graph
                await self._update_graph_relationship(correlation)
                
                # Escalate confidence
                await self._escalate_confidence(
                    correlation.wallet_a,
                    correlation.wallet_b,
                    len(matching_wallets),
                )
        
        # Update or create cluster
        if results:
            await self._update_cluster(event.contract_address, matching_wallets)
        
        return results
    
    async def _find_correlated_wallets(
        self, 
        event: CorrelationEvent
    ) -> List[CorrelationEvent]:
        """
        Find wallets that interacted with the same contract within the block window.
        """
        slot_min = event.slot - self.config.BLOCK_WINDOW
        slot_max = event.slot + self.config.BLOCK_WINDOW
        
        # First check cache
        cached_events = []
        for slot in range(slot_min, slot_max + 1):
            if slot in self._event_cache:
                for cached_event in self._event_cache[slot]:
                    if cached_event.contract_address == event.contract_address:
                        cached_events.append(cached_event)
        
        if cached_events:
            return cached_events[:self.config.MAX_WALLETS_PER_EVENT]
        
        # Query database for historical events
        query = """
            SELECT 
                wallet_address,
                tx_hash,
                slot,
                event_time,
                action,
                program_id as contract_address
            FROM tx_events
            WHERE program_id = $1
              AND slot BETWEEN $2 AND $3
            ORDER BY slot ASC
            LIMIT $4
        """
        
        try:
            results = await self.db.fetch(
                query,
                event.contract_address,
                slot_min,
                slot_max,
                self.config.MAX_WALLETS_PER_EVENT,
            )
            
            return [
                CorrelationEvent(
                    contract_address=row["contract_address"],
                    slot=row["slot"],
                    timestamp=row["event_time"],
                    wallet_address=row["wallet_address"],
                    tx_hash=row["tx_hash"],
                    action=row.get("action", "unknown"),
                )
                for row in results
            ]
        except Exception as e:
            logger.error(f"Database query failed: {e}")
            return []
    
    async def _calculate_correlation(
        self,
        event_a: CorrelationEvent,
        event_b: CorrelationEvent,
    ) -> CorrelationResult:
        """
        Calculate correlation score between two wallet events.
        
        Score = (time_weight × time_score) + (order_weight × order_score) + (history_weight × history_score)
        """
        wallet_a = event_a.wallet_address
        wallet_b = event_b.wallet_address
        
        # Time proximity score (closer = higher)
        time_delta_ms = abs(
            (event_a.timestamp - event_b.timestamp).total_seconds() * 1000
        )
        max_time_ms = self.config.BLOCK_WINDOW * 400  # ~400ms per slot
        time_score = Decimal("1") - min(
            Decimal("1"),
            Decimal(str(time_delta_ms)) / Decimal(str(max_time_ms))
        )
        
        # Transaction ordering score (consistent ordering = higher)
        # Query historical ordering patterns
        order_score = await self._calculate_order_score(wallet_a, wallet_b)
        
        # Historical co-occurrence score
        shared_contracts, co_occurrence_count = await self._get_shared_history(
            wallet_a, wallet_b
        )
        
        # More shared contracts = higher score (capped at 1.0)
        history_score = min(
            Decimal("1"),
            Decimal(str(len(shared_contracts))) / Decimal(str(self.config.SHARED_CONTRACTS_STRONG))
        )
        
        # Calculate weighted final score
        correlation_score = (
            (self.config.TIME_PROXIMITY_WEIGHT * time_score) +
            (self.config.TX_ORDER_WEIGHT * order_score) +
            (self.config.HISTORY_WEIGHT * history_score)
        )
        
        return CorrelationResult(
            wallet_a=wallet_a,
            wallet_b=wallet_b,
            correlation_score=min(Decimal("1"), correlation_score),
            shared_contracts=shared_contracts,
            time_proximity_avg_ms=time_delta_ms,
            co_occurrence_count=co_occurrence_count,
            contract_address=event_a.contract_address,
        )
    
    async def _calculate_order_score(
        self, 
        wallet_a: str, 
        wallet_b: str
    ) -> Decimal:
        """
        Calculate transaction ordering consistency score.
        
        If wallet_a consistently transacts before wallet_b (or vice versa),
        this indicates potential coordination.
        """
        query = """
            WITH paired_txs AS (
                SELECT 
                    a.program_id,
                    a.slot as slot_a,
                    b.slot as slot_b,
                    CASE WHEN a.slot < b.slot THEN 1 ELSE 0 END as a_first
                FROM tx_events a
                JOIN tx_events b ON a.program_id = b.program_id
                    AND a.wallet_address = $1
                    AND b.wallet_address = $2
                    AND ABS(a.slot - b.slot) <= $3
                LIMIT 100
            )
            SELECT 
                COUNT(*) as total_pairs,
                SUM(a_first) as a_first_count
            FROM paired_txs
        """
        
        try:
            results = await self.db.fetch(
                query, 
                wallet_a, 
                wallet_b, 
                self.config.BLOCK_WINDOW
            )
            
            if not results or results[0]["total_pairs"] == 0:
                return Decimal("0.5")  # Neutral score if no history
            
            row = results[0]
            total = row["total_pairs"]
            a_first = row["a_first_count"]
            
            # Higher score if ordering is consistent (mostly A first or mostly B first)
            consistency = abs(a_first / total - 0.5) * 2  # 0 to 1 scale
            return Decimal(str(consistency))
            
        except Exception as e:
            logger.error(f"Order score calculation failed: {e}")
            return Decimal("0.5")
    
    async def _get_shared_history(
        self, 
        wallet_a: str, 
        wallet_b: str
    ) -> Tuple[List[str], int]:
        """
        Get shared contract history between two wallets.
        
        Returns:
            Tuple of (list of shared contract addresses, co-occurrence count)
        """
        query = """
            SELECT 
                a.program_id as contract,
                COUNT(*) as co_occurrences
            FROM tx_events a
            JOIN tx_events b ON a.program_id = b.program_id
                AND a.wallet_address = $1
                AND b.wallet_address = $2
                AND ABS(a.slot - b.slot) <= $3
            GROUP BY a.program_id
            ORDER BY co_occurrences DESC
            LIMIT 20
        """
        
        try:
            results = await self.db.fetch(
                query, 
                wallet_a, 
                wallet_b, 
                self.config.BLOCK_WINDOW * 5  # Wider window for history
            )
            
            shared_contracts = [row["contract"] for row in results]
            total_co_occurrences = sum(row["co_occurrences"] for row in results)
            
            return shared_contracts, total_co_occurrences
            
        except Exception as e:
            logger.error(f"Shared history query failed: {e}")
            return [], 0
    
    async def _update_graph_relationship(
        self, 
        result: CorrelationResult
    ) -> None:
        """Create or update CORRELATED_WITH relationship in Neo4j."""
        query = """
            MERGE (a:Wallet {address: $wallet_a})
            MERGE (b:Wallet {address: $wallet_b})
            MERGE (a)-[r:CORRELATED_WITH]->(b)
            SET r.correlation_score = $correlation_score,
                r.shared_contracts = $shared_contracts,
                r.time_proximity_avg = $time_proximity_avg,
                r.co_occurrence_count = $co_occurrence_count,
                r.updated_at = datetime($detected_at)
        """
        
        try:
            await self.graph.run(query, **result.to_neo4j_params())
            logger.debug(
                f"Updated graph: {result.wallet_a[:12]}... <-> "
                f"{result.wallet_b[:12]}... (score: {result.correlation_score:.3f})"
            )
        except Exception as e:
            logger.error(f"Graph update failed: {e}")
    
    async def _escalate_confidence(
        self,
        wallet_a: str,
        wallet_b: str,
        cluster_size: int,
    ) -> None:
        """
        Escalate confidence scores for correlated wallets.
        
        new_confidence = min(1.0, old_confidence + (ESCALATION_BASE × N/10))
        """
        escalation = float(self.config.ESCALATION_BASE) * (cluster_size / 10)
        
        for wallet in [wallet_a, wallet_b]:
            query = """
                UPDATE tracked_wallets
                SET confidence = LEAST(1.0, confidence + $1),
                    last_activity = NOW()
                WHERE address = $2
            """
            try:
                await self.db.execute(query, escalation, wallet)
            except Exception as e:
                logger.error(f"Confidence escalation failed for {wallet}: {e}")
    
    async def _update_cluster(
        self,
        contract_address: str,
        events: List[CorrelationEvent],
    ) -> None:
        """Update or create a wallet cluster based on correlated events."""
        wallet_addresses = {e.wallet_address for e in events}
        
        # Check if any wallets are already in a cluster
        existing_cluster_id = None
        for wallet in wallet_addresses:
            if wallet in self._wallet_clusters:
                existing_cluster_id = self._wallet_clusters[wallet]
                break
        
        if existing_cluster_id and existing_cluster_id in self._clusters:
            cluster = self._clusters[existing_cluster_id]
            for wallet in wallet_addresses:
                cluster.add_wallet(wallet)
                self._wallet_clusters[wallet] = cluster.cluster_id
            cluster.add_shared_contract(contract_address)
            cluster.total_interactions += len(events)
        else:
            # Create new cluster
            cluster_id = str(uuid.uuid4())
            cluster = WalletCluster(
                cluster_id=cluster_id,
                wallets=wallet_addresses,
                shared_contracts={contract_address},
                total_interactions=len(events),
            )
            self._clusters[cluster_id] = cluster
            for wallet in wallet_addresses:
                self._wallet_clusters[wallet] = cluster_id
        
        # Persist cluster to Neo4j
        await self._persist_cluster(cluster)
    
    async def _persist_cluster(self, cluster: WalletCluster) -> None:
        """Persist a cluster to Neo4j."""
        query = """
            MERGE (c:Cluster {cluster_id: $cluster_id})
            SET c.member_count = $member_count,
                c.shared_contracts_count = $shared_contracts_count,
                c.updated_at = datetime($updated_at)
            WITH c
            UNWIND $wallets AS wallet_addr
            MERGE (w:Wallet {address: wallet_addr})
            MERGE (w)-[:MEMBER_OF]->(c)
        """
        
        try:
            await self.graph.run(
                query,
                cluster_id=cluster.cluster_id,
                member_count=cluster.size,
                shared_contracts_count=len(cluster.shared_contracts),
                updated_at=cluster.updated_at.isoformat(),
                wallets=list(cluster.wallets),
            )
            logger.info(
                f"Updated cluster {cluster.cluster_id[:8]}... "
                f"({cluster.size} wallets)"
            )
        except Exception as e:
            logger.error(f"Cluster persistence failed: {e}")
    
    def _cache_event(self, event: CorrelationEvent) -> None:
        """Cache an event for recent lookup."""
        self._event_cache[event.slot].append(event)
        
        # Evict old slots
        if len(self._event_cache) > self._cache_max_slots:
            oldest_slot = min(self._event_cache.keys())
            del self._event_cache[oldest_slot]
    
    def get_cluster_for_wallet(self, wallet_address: str) -> Optional[WalletCluster]:
        """Get the cluster containing a wallet, if any."""
        cluster_id = self._wallet_clusters.get(wallet_address)
        if cluster_id:
            return self._clusters.get(cluster_id)
        return None
    
    @property
    def active_clusters(self) -> List[WalletCluster]:
        """Get all clusters that meet cabal criteria."""
        return [c for c in self._clusters.values() if c.is_active_cabal]
