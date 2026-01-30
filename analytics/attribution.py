"""Signal Attribution - Track performance by signal source."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Protocol
import logging

logger = logging.getLogger(__name__)


@dataclass
class SourceStats:
    """Performance statistics for a signal source."""
    
    source_id: str
    source_type: str  # "cabal", "influencer", "fresh_wallet"
    source_name: Optional[str] = None
    
    # Trade counts
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # P&L
    total_pnl: Decimal = Decimal("0")
    avg_pnl_percentage: Decimal = Decimal("0")
    best_trade_pnl: Optional[Decimal] = None
    worst_trade_pnl: Optional[Decimal] = None
    
    # Rates
    win_rate: Decimal = Decimal("0")
    avg_hold_time_hours: Optional[float] = None
    
    # Risk metrics
    sharpe_ratio: Optional[Decimal] = None
    sortino_ratio: Optional[Decimal] = None
    max_drawdown: Optional[Decimal] = None
    
    last_trade_time: Optional[datetime] = None
    
    @property
    def profit_factor(self) -> Optional[Decimal]:
        """Gross profit / gross loss."""
        if self.worst_trade_pnl and self.worst_trade_pnl < 0:
            gross_loss = abs(self.worst_trade_pnl) * self.losing_trades
            if gross_loss > 0:
                gross_profit = self.best_trade_pnl * self.winning_trades if self.best_trade_pnl else Decimal("0")
                return gross_profit / gross_loss
        return None
    
    @property
    def roi(self) -> Decimal:
        """Return on investment percentage."""
        return self.avg_pnl_percentage * Decimal(str(self.total_trades))


class DatabaseClient(Protocol):
    """Protocol for database client."""
    async def fetch(self, query: str, *args) -> list: ...
    async def execute(self, query: str, *args) -> None: ...


class SignalAttribution:
    """
    Tracks performance by signal source for attribution analysis.
    
    Answers questions like:
    - Which influencer generates the best signals?
    - Which cabal has the highest win rate?
    - Which signal type is most profitable?
    
    Features:
    - Real-time stats updates
    - Leaderboard ranking
    - Historical performance tracking
    """
    
    def __init__(self, db_client: DatabaseClient):
        """
        Initialize signal attribution.
        
        Args:
            db_client: Database client for persistence
        """
        self.db = db_client
    
    async def update_source_stats(
        self,
        source_id: str,
        source_type: str,
        pnl: Decimal,
        is_win: bool,
        hold_time_hours: float = None,
        source_name: str = None,
    ) -> None:
        """
        Update statistics for a signal source after a trade.
        
        Args:
            source_id: Unique identifier for the source
            source_type: Type of source (cabal, influencer, etc.)
            pnl: Realized P&L from the trade
            is_win: Whether the trade was profitable
            hold_time_hours: Duration of the trade
            source_name: Optional human-readable name
        """
        # Check if source exists
        check_query = "SELECT 1 FROM signal_attribution WHERE source_id = $1"
        results = await self.db.fetch(check_query, source_id)
        
        if not results:
            # Create new source entry
            insert_query = """
                INSERT INTO signal_attribution (
                    source_id, source_type, source_name,
                    total_trades, winning_trades, losing_trades,
                    total_pnl, best_trade_pnl, worst_trade_pnl,
                    last_trade_time
                ) VALUES ($1, $2, $3, 1, $4, $5, $6, $7, $8, NOW())
            """
            await self.db.execute(
                insert_query,
                source_id,
                source_type,
                source_name,
                1 if is_win else 0,
                0 if is_win else 1,
                pnl,
                pnl if is_win else None,
                pnl if not is_win else None,
            )
        else:
            # Update existing source
            update_query = """
                UPDATE signal_attribution
                SET total_trades = total_trades + 1,
                    winning_trades = winning_trades + $1,
                    losing_trades = losing_trades + $2,
                    total_pnl = total_pnl + $3,
                    avg_pnl_percentage = (total_pnl + $3) / (total_trades + 1),
                    win_rate = (winning_trades + $1)::DECIMAL / (total_trades + 1),
                    best_trade_pnl = GREATEST(COALESCE(best_trade_pnl, $3), $3),
                    worst_trade_pnl = LEAST(COALESCE(worst_trade_pnl, $3), $3),
                    last_trade_time = NOW(),
                    last_updated = NOW()
                WHERE source_id = $4
            """
            await self.db.execute(
                update_query,
                1 if is_win else 0,
                0 if is_win else 1,
                pnl,
                source_id,
            )
        
        logger.debug(f"Updated stats for {source_type}:{source_id}")
    
    async def get_source_stats(self, source_id: str) -> Optional[SourceStats]:
        """Get statistics for a specific source."""
        query = "SELECT * FROM signal_attribution WHERE source_id = $1"
        
        try:
            results = await self.db.fetch(query, source_id)
            if results:
                return self._row_to_stats(results[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get source stats: {e}")
            return None
    
    async def get_leaderboard(
        self,
        source_type: str = None,
        min_trades: int = 5,
        limit: int = 20,
    ) -> List[SourceStats]:
        """
        Get top performing sources ranked by win rate.
        
        Args:
            source_type: Optional filter by source type
            min_trades: Minimum trades to be included
            limit: Maximum results to return
            
        Returns:
            List of SourceStats ordered by win rate descending
        """
        query = """
            SELECT * FROM signal_attribution
            WHERE total_trades >= $1
        """
        params = [min_trades]
        
        if source_type:
            query += " AND source_type = $2"
            params.append(source_type)
        
        query += " ORDER BY win_rate DESC, total_pnl DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)
        
        try:
            results = await self.db.fetch(query, *params)
            return [self._row_to_stats(row) for row in results]
        except Exception as e:
            logger.error(f"Failed to get leaderboard: {e}")
            return []
    
    async def get_type_summary(self) -> dict:
        """Get aggregate statistics by source type."""
        query = """
            SELECT 
                source_type,
                COUNT(*) as source_count,
                SUM(total_trades) as total_trades,
                SUM(winning_trades) as winning_trades,
                SUM(total_pnl) as total_pnl,
                AVG(win_rate) as avg_win_rate
            FROM signal_attribution
            GROUP BY source_type
            ORDER BY total_pnl DESC
        """
        
        try:
            results = await self.db.fetch(query)
            return {
                row["source_type"]: {
                    "sources": row["source_count"],
                    "trades": row["total_trades"],
                    "wins": row["winning_trades"],
                    "pnl": Decimal(str(row["total_pnl"] or 0)),
                    "avg_win_rate": Decimal(str(row["avg_win_rate"] or 0)),
                }
                for row in results
            }
        except Exception as e:
            logger.error(f"Failed to get type summary: {e}")
            return {}
    
    async def get_hot_sources(
        self,
        hours: int = 24,
        min_win_rate: float = 0.6,
    ) -> List[SourceStats]:
        """
        Get sources with recent high performance.
        
        Args:
            hours: Look-back period
            min_win_rate: Minimum win rate to include
            
        Returns:
            List of hot performing sources
        """
        query = """
            SELECT * FROM signal_attribution
            WHERE last_trade_time > NOW() - INTERVAL '%s hours'
              AND win_rate >= $1
              AND total_trades >= 3
            ORDER BY win_rate DESC, total_pnl DESC
            LIMIT 10
        """ % hours
        
        try:
            results = await self.db.fetch(query, Decimal(str(min_win_rate)))
            return [self._row_to_stats(row) for row in results]
        except Exception as e:
            logger.error(f"Failed to get hot sources: {e}")
            return []
    
    def _row_to_stats(self, row: dict) -> SourceStats:
        """Convert database row to SourceStats."""
        return SourceStats(
            source_id=row["source_id"],
            source_type=row["source_type"],
            source_name=row.get("source_name"),
            total_trades=row["total_trades"] or 0,
            winning_trades=row["winning_trades"] or 0,
            losing_trades=row["losing_trades"] or 0,
            total_pnl=Decimal(str(row["total_pnl"] or 0)),
            avg_pnl_percentage=Decimal(str(row["avg_pnl_percentage"] or 0)),
            win_rate=Decimal(str(row["win_rate"] or 0)),
            best_trade_pnl=Decimal(str(row["best_trade_pnl"])) if row.get("best_trade_pnl") else None,
            worst_trade_pnl=Decimal(str(row["worst_trade_pnl"])) if row.get("worst_trade_pnl") else None,
            sharpe_ratio=Decimal(str(row["sharpe_ratio"])) if row.get("sharpe_ratio") else None,
            last_trade_time=row.get("last_trade_time"),
        )
