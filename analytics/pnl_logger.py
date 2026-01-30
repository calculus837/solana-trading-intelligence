"""PnL Logger - Trade result logging and tracking."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Protocol
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TradeStatus(str, Enum):
    """Status of a trade."""
    OPEN = "open"
    CLOSED = "closed"
    STOPPED_OUT = "stopped_out"
    RUGGED = "rugged"
    PANIC_SOLD = "panic_sold"


@dataclass
class TradeLog:
    """Complete log of a trade from entry to exit."""
    
    trade_id: str
    signal_source: str
    signal_id: Optional[str]
    token_mint: str
    
    # Entry
    entry_price: Optional[Decimal] = None
    entry_time: Optional[datetime] = None
    position_size: Decimal = Decimal("0")
    position_size_sol: Decimal = Decimal("0")
    
    # Exit
    exit_price: Optional[Decimal] = None
    exit_time: Optional[datetime] = None
    exit_tier: Optional[str] = None
    
    # P&L
    realized_pnl: Optional[Decimal] = None
    pnl_percentage: Optional[Decimal] = None
    fees_paid: Decimal = Decimal("0")
    priority_fee: Decimal = Decimal("0")
    
    # Status
    status: TradeStatus = TradeStatus.OPEN
    failure_reason: Optional[str] = None
    
    # Execution
    sub_wallet_address: Optional[str] = None
    jito_bundle_id: Optional[str] = None
    slippage_expected: Optional[Decimal] = None
    slippage_actual: Optional[Decimal] = None
    
    @property
    def is_win(self) -> bool:
        """Returns True if trade was profitable."""
        return self.realized_pnl is not None and self.realized_pnl > 0
    
    @property
    def hold_duration(self) -> Optional[float]:
        """Duration in hours from entry to exit."""
        if self.entry_time and self.exit_time:
            delta = self.exit_time - self.entry_time
            return delta.total_seconds() / 3600
        return None
    
    @property
    def net_pnl(self) -> Decimal:
        """Net P&L after fees."""
        pnl = self.realized_pnl or Decimal("0")
        return pnl - self.fees_paid - self.priority_fee


class DatabaseClient(Protocol):
    """Protocol for database client."""
    async def fetch(self, query: str, *args) -> list: ...
    async def execute(self, query: str, *args) -> None: ...


class PnLLogger:
    """
    Logs and tracks trade P&L for analysis.
    
    Features:
    - Full trade lifecycle logging
    - Real-time P&L calculation
    - Historical trade queries
    - Summary statistics
    """
    
    def __init__(self, db_client: DatabaseClient):
        """
        Initialize P&L logger.
        
        Args:
            db_client: Database client for persistence
        """
        self.db = db_client
    
    async def log_entry(
        self,
        trade_id: str,
        signal_source: str,
        token_mint: str,
        entry_price: Decimal,
        position_size: Decimal,
        signal_id: str = None,
        sub_wallet: str = None,
    ) -> None:
        """Log a trade entry."""
        query = """
            INSERT INTO trade_log (
                trade_id, signal_source, signal_id, token_mint,
                entry_price, entry_time, position_size, position_size_sol,
                sub_wallet_address, status
            ) VALUES ($1, $2, $3, $4, $5, NOW(), $6, $7, $8, 'open')
        """
        
        try:
            import uuid
            await self.db.execute(
                query,
                uuid.UUID(trade_id),
                signal_source,
                uuid.UUID(signal_id) if signal_id else None,
                token_mint,
                entry_price,
                position_size,
                position_size,
                sub_wallet,
            )
            logger.info(f"Logged trade entry: {trade_id[:8]}...")
        except Exception as e:
            logger.error(f"Failed to log trade entry: {e}")
    
    async def log_exit(
        self,
        trade_id: str,
        exit_price: Decimal,
        exit_tier: str,
        status: TradeStatus = TradeStatus.CLOSED,
        failure_reason: str = None,
    ) -> None:
        """Log a trade exit."""
        # First get entry info for P&L calculation
        entry_query = """
            SELECT entry_price, position_size, fees_paid
            FROM trade_log
            WHERE trade_id = $1
        """
        
        try:
            import uuid
            results = await self.db.fetch(entry_query, uuid.UUID(trade_id))
            
            if not results:
                logger.error(f"Trade not found: {trade_id}")
                return
            
            row = results[0]
            entry_price = Decimal(str(row["entry_price"]))
            position_size = Decimal(str(row["position_size"]))
            fees = Decimal(str(row["fees_paid"] or 0))
            
            # Calculate P&L
            if entry_price > 0:
                pnl = (exit_price - entry_price) * position_size
                pnl_pct = (exit_price - entry_price) / entry_price
            else:
                pnl = Decimal("0")
                pnl_pct = Decimal("0")
            
            # Update trade log
            update_query = """
                UPDATE trade_log
                SET exit_price = $1,
                    exit_time = NOW(),
                    exit_tier = $2,
                    realized_pnl = $3,
                    pnl_percentage = $4,
                    status = $5,
                    failure_reason = $6
                WHERE trade_id = $7
            """
            
            await self.db.execute(
                update_query,
                exit_price,
                exit_tier,
                pnl,
                pnl_pct,
                status.value,
                failure_reason,
                uuid.UUID(trade_id),
            )
            
            logger.info(
                f"Logged trade exit: {trade_id[:8]}... | "
                f"PnL: {pnl:.4f} ({pnl_pct:.2%})"
            )
            
        except Exception as e:
            logger.error(f"Failed to log trade exit: {e}")
    
    async def get_trade(self, trade_id: str) -> Optional[TradeLog]:
        """Get a specific trade by ID."""
        query = """
            SELECT * FROM trade_log WHERE trade_id = $1
        """
        
        try:
            import uuid
            results = await self.db.fetch(query, uuid.UUID(trade_id))
            
            if results:
                return self._row_to_trade_log(results[0])
            return None
            
        except Exception as e:
            logger.error(f"Failed to get trade: {e}")
            return None
    
    async def get_open_trades(self) -> List[TradeLog]:
        """Get all open trades."""
        query = """
            SELECT * FROM trade_log
            WHERE status = 'open'
            ORDER BY entry_time DESC
        """
        
        try:
            results = await self.db.fetch(query)
            return [self._row_to_trade_log(row) for row in results]
        except Exception as e:
            logger.error(f"Failed to get open trades: {e}")
            return []
    
    async def get_daily_summary(self) -> dict:
        """Get daily P&L summary."""
        query = """
            SELECT 
                COUNT(*) as total_trades,
                COUNT(*) FILTER (WHERE realized_pnl > 0) as winning_trades,
                COUNT(*) FILTER (WHERE realized_pnl <= 0) as losing_trades,
                COALESCE(SUM(realized_pnl), 0) as total_pnl,
                COALESCE(AVG(pnl_percentage), 0) as avg_pnl_pct,
                COALESCE(SUM(fees_paid), 0) as total_fees
            FROM trade_log
            WHERE entry_time >= CURRENT_DATE
              AND status != 'open'
        """
        
        try:
            results = await self.db.fetch(query)
            if results:
                row = results[0]
                total = row["total_trades"] or 0
                wins = row["winning_trades"] or 0
                
                return {
                    "total_trades": total,
                    "winning_trades": wins,
                    "losing_trades": row["losing_trades"] or 0,
                    "win_rate": wins / total if total > 0 else 0,
                    "total_pnl": Decimal(str(row["total_pnl"])),
                    "avg_pnl_pct": Decimal(str(row["avg_pnl_pct"])),
                    "total_fees": Decimal(str(row["total_fees"])),
                }
        except Exception as e:
            logger.error(f"Failed to get daily summary: {e}")
        
        return {}
    
    def _row_to_trade_log(self, row: dict) -> TradeLog:
        """Convert database row to TradeLog."""
        return TradeLog(
            trade_id=str(row["trade_id"]),
            signal_source=row["signal_source"],
            signal_id=str(row["signal_id"]) if row.get("signal_id") else None,
            token_mint=row["token_mint"],
            entry_price=Decimal(str(row["entry_price"])) if row.get("entry_price") else None,
            entry_time=row.get("entry_time"),
            position_size=Decimal(str(row["position_size"])) if row.get("position_size") else Decimal("0"),
            exit_price=Decimal(str(row["exit_price"])) if row.get("exit_price") else None,
            exit_time=row.get("exit_time"),
            exit_tier=row.get("exit_tier"),
            realized_pnl=Decimal(str(row["realized_pnl"])) if row.get("realized_pnl") else None,
            pnl_percentage=Decimal(str(row["pnl_percentage"])) if row.get("pnl_percentage") else None,
            fees_paid=Decimal(str(row["fees_paid"] or 0)),
            status=TradeStatus(row["status"]),
            failure_reason=row.get("failure_reason"),
            sub_wallet_address=row.get("sub_wallet_address"),
        )
