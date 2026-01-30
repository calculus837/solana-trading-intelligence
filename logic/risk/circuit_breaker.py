"""Circuit Breaker - Global risk management and emergency controls."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Protocol
from enum import Enum
import logging
import asyncio

logger = logging.getLogger(__name__)


class TradeStatus(str, Enum):
    """Status of a trade position."""
    OPEN = "open"
    CLOSED = "closed"
    STOPPED_OUT = "stopped_out"
    RUGGED = "rugged"
    PANIC_SOLD = "panic_sold"


@dataclass
class RiskLimits:
    """Configurable risk limits for the circuit breaker."""
    
    # Maximum allowed daily drawdown as percentage of capital
    max_daily_drawdown_pct: Decimal = Decimal("0.10")  # 10%
    
    # Maximum allowed loss per single trade
    max_single_trade_pct: Decimal = Decimal("0.02")  # 2%
    
    # Maximum position size as percentage of capital
    max_position_size_pct: Decimal = Decimal("0.05")  # 5%
    
    # Maximum number of concurrent open positions
    max_open_positions: int = 10
    
    # Consecutive losses to trigger lockdown
    max_consecutive_losses: int = 3
    
    # Lockdown duration in hours
    lockdown_hours: int = 24


@dataclass
class LockdownState:
    """Current state of the circuit breaker."""
    
    is_locked: bool = False
    locked_at: Optional[datetime] = None
    lock_reason: Optional[str] = None
    unlock_at: Optional[datetime] = None
    daily_pnl: Decimal = Decimal("0")
    daily_pnl_pct: Decimal = Decimal("0")
    consecutive_losses: int = 0
    open_position_count: int = 0
    total_exposure: Decimal = Decimal("0")
    last_trade_time: Optional[datetime] = None


class DatabaseClient(Protocol):
    """Protocol for database client interface."""
    async def fetch(self, query: str, *args) -> list: ...
    async def execute(self, query: str, *args) -> None: ...


class CircuitBreaker:
    """
    Global risk management and emergency circuit breaker.
    
    This class monitors trading activity and enforces risk limits:
    - Daily drawdown limits
    - Per-trade loss limits
    - Position size limits
    - Maximum open positions
    - Consecutive loss limits
    
    When limits are breached, the circuit breaker enters lockdown mode
    and can trigger a panic sell of all open positions.
    
    Usage:
        breaker = CircuitBreaker(db_client, capital=1000.0)
        
        # Before opening a trade
        if not await breaker.can_trade():
            return "Trading halted"
        
        if not await breaker.validate_position_size(size):
            return "Position too large"
        
        # After a loss
        await breaker.record_trade_result(pnl=-50.0, is_win=False)
        
        # Emergency
        await breaker.panic_sell_all()
    """
    
    def __init__(
        self,
        db_client: DatabaseClient,
        capital: float,
        limits: RiskLimits = None,
    ):
        """
        Initialize the circuit breaker.
        
        Args:
            db_client: Database client for state persistence
            capital: Total trading capital in USD/SOL
            limits: Risk limit configuration
        """
        self.db = db_client
        self.capital = Decimal(str(capital))
        self.limits = limits or RiskLimits()
        self._state: Optional[LockdownState] = None
        self._lock = asyncio.Lock()
    
    async def load_state(self) -> LockdownState:
        """Load circuit breaker state from database."""
        query = """
            SELECT 
                is_locked, locked_at, lock_reason, unlock_at,
                daily_pnl, daily_pnl_pct, consecutive_losses,
                open_position_count, total_exposure, last_trade_time
            FROM circuit_breaker_state
            WHERE id = 1
        """
        
        try:
            results = await self.db.fetch(query)
            if results:
                row = results[0]
                self._state = LockdownState(
                    is_locked=row["is_locked"],
                    locked_at=row["locked_at"],
                    lock_reason=row["lock_reason"],
                    unlock_at=row["unlock_at"],
                    daily_pnl=Decimal(str(row["daily_pnl"] or 0)),
                    daily_pnl_pct=Decimal(str(row["daily_pnl_pct"] or 0)),
                    consecutive_losses=row["consecutive_losses"] or 0,
                    open_position_count=row["open_position_count"] or 0,
                    total_exposure=Decimal(str(row["total_exposure"] or 0)),
                    last_trade_time=row["last_trade_time"],
                )
        except Exception as e:
            logger.error(f"Failed to load circuit breaker state: {e}")
            self._state = LockdownState()
        
        return self._state
    
    async def save_state(self) -> None:
        """Persist circuit breaker state to database."""
        if not self._state:
            return
        
        query = """
            UPDATE circuit_breaker_state SET
                is_locked = $1,
                locked_at = $2,
                lock_reason = $3,
                unlock_at = $4,
                daily_pnl = $5,
                daily_pnl_pct = $6,
                consecutive_losses = $7,
                open_position_count = $8,
                total_exposure = $9,
                last_trade_time = $10,
                updated_at = NOW()
            WHERE id = 1
        """
        
        try:
            await self.db.execute(
                query,
                self._state.is_locked,
                self._state.locked_at,
                self._state.lock_reason,
                self._state.unlock_at,
                self._state.daily_pnl,
                self._state.daily_pnl_pct,
                self._state.consecutive_losses,
                self._state.open_position_count,
                self._state.total_exposure,
                self._state.last_trade_time,
            )
        except Exception as e:
            logger.error(f"Failed to save circuit breaker state: {e}")
    
    async def can_trade(self) -> bool:
        """
        Check if trading is currently allowed.
        
        Returns:
            True if trading is allowed, False if locked
        """
        async with self._lock:
            if not self._state:
                await self.load_state()
            
            # Check if currently locked
            if self._state.is_locked:
                # Check if lockdown period has expired
                if self._state.unlock_at and datetime.now(timezone.utc) > self._state.unlock_at:
                    await self._unlock()
                    return True
                return False
            
            # Check if max open positions reached
            if self._state.open_position_count >= self.limits.max_open_positions:
                logger.warning(
                    f"Max open positions reached: {self._state.open_position_count}"
                )
                return False
            
            return True
    
    async def validate_position_size(self, size_sol: float) -> bool:
        """
        Validate that a position size is within limits.
        
        Args:
            size_sol: Position size in SOL
            
        Returns:
            True if size is acceptable, False if too large
        """
        max_size = self.capital * self.limits.max_position_size_pct
        
        if Decimal(str(size_sol)) > max_size:
            logger.warning(
                f"Position size {size_sol} exceeds max {max_size}"
            )
            return False
        
        return True
    
    async def record_trade_result(
        self,
        pnl: float,
        is_win: bool,
        position_size: float = 0,
    ) -> bool:
        """
        Record a trade result and check if limits are breached.
        
        Args:
            pnl: Realized P&L from the trade
            is_win: Whether the trade was profitable
            position_size: Size of the closed position
            
        Returns:
            True if within limits, False if lockdown triggered
        """
        async with self._lock:
            if not self._state:
                await self.load_state()
            
            pnl_decimal = Decimal(str(pnl))
            
            # Update daily P&L
            self._state.daily_pnl += pnl_decimal
            self._state.daily_pnl_pct = self._state.daily_pnl / self.capital
            
            # Update consecutive losses
            if is_win:
                self._state.consecutive_losses = 0
            else:
                self._state.consecutive_losses += 1
            
            # Decrease open position count
            if self._state.open_position_count > 0:
                self._state.open_position_count -= 1
            
            # Update exposure
            self._state.total_exposure -= Decimal(str(position_size))
            self._state.last_trade_time = datetime.now(timezone.utc)
            
            # Check for breaches
            should_lock = False
            lock_reason = None
            
            # Daily drawdown check
            if abs(self._state.daily_pnl_pct) > self.limits.max_daily_drawdown_pct:
                should_lock = True
                lock_reason = f"Daily drawdown exceeded: {self._state.daily_pnl_pct:.2%}"
            
            # Consecutive losses check
            elif self._state.consecutive_losses >= self.limits.max_consecutive_losses:
                should_lock = True
                lock_reason = f"Consecutive losses: {self._state.consecutive_losses}"
            
            if should_lock:
                await self._trigger_lockdown(lock_reason)
                await self.save_state()
                return False
            
            await self.save_state()
            return True
    
    async def record_position_opened(self, size_sol: float) -> None:
        """Record that a new position was opened."""
        async with self._lock:
            if not self._state:
                await self.load_state()
            
            self._state.open_position_count += 1
            self._state.total_exposure += Decimal(str(size_sol))
            await self.save_state()
    
    async def _trigger_lockdown(self, reason: str) -> None:
        """Trigger lockdown mode."""
        now = datetime.now(timezone.utc)
        unlock_at = now + timedelta(hours=self.limits.lockdown_hours)
        
        self._state.is_locked = True
        self._state.locked_at = now
        self._state.lock_reason = reason
        self._state.unlock_at = unlock_at
        
        logger.critical(
            f"🚨 CIRCUIT BREAKER TRIGGERED: {reason} | "
            f"Lockdown until {unlock_at}"
        )
    
    async def _unlock(self) -> None:
        """Unlock from lockdown mode."""
        self._state.is_locked = False
        self._state.locked_at = None
        self._state.lock_reason = None
        self._state.unlock_at = None
        # Reset daily stats on unlock
        self._state.daily_pnl = Decimal("0")
        self._state.daily_pnl_pct = Decimal("0")
        self._state.consecutive_losses = 0
        
        await self.save_state()
        logger.info("Circuit breaker unlocked - trading resumed")
    
    async def panic_sell_all(self) -> List[dict]:
        """
        Emergency sell all open positions.
        
        Returns:
            List of sell results for each position
        """
        logger.critical("🚨 PANIC SELL INITIATED - Selling all positions")
        
        # Trigger lockdown
        await self._trigger_lockdown("Manual panic sell")
        
        # Get all open positions
        query = """
            SELECT trade_id, token_mint, position_size, sub_wallet_address
            FROM trade_log
            WHERE status = 'open'
        """
        
        results = []
        try:
            positions = await self.db.fetch(query)
            
            for pos in positions:
                # Mark as panic sold
                update_query = """
                    UPDATE trade_log
                    SET status = 'panic_sold',
                        exit_time = NOW(),
                        exit_tier = 'PANIC'
                    WHERE trade_id = $1
                """
                await self.db.execute(update_query, pos["trade_id"])
                
                results.append({
                    "trade_id": str(pos["trade_id"]),
                    "token_mint": pos["token_mint"],
                    "status": "marked_for_sell",
                })
                
                logger.info(f"Marked for panic sell: {pos['token_mint'][:16]}...")
            
            self._state.open_position_count = 0
            self._state.total_exposure = Decimal("0")
            await self.save_state()
            
        except Exception as e:
            logger.error(f"Panic sell failed: {e}")
        
        return results
    
    async def force_unlock(self) -> None:
        """Manually unlock the circuit breaker (use with caution)."""
        async with self._lock:
            if not self._state:
                await self.load_state()
            
            await self._unlock()
            logger.warning("Circuit breaker manually unlocked")
    
    async def reset_daily_stats(self) -> None:
        """Reset daily statistics (call at midnight UTC)."""
        async with self._lock:
            if not self._state:
                await self.load_state()
            
            self._state.daily_pnl = Decimal("0")
            self._state.daily_pnl_pct = Decimal("0")
            await self.save_state()
            
            logger.info("Daily statistics reset")
    
    @property
    def is_locked(self) -> bool:
        """Check if circuit breaker is currently locked."""
        return self._state.is_locked if self._state else False
    
    @property
    def state(self) -> Optional[LockdownState]:
        """Get current circuit breaker state."""
        return self._state
