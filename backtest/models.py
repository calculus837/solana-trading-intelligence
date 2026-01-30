"""Data models for backtesting engine."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Optional, List
from enum import Enum


class SignalType(Enum):
    """Type of trading signal detected."""
    INFLUENCER = "influencer"
    CABAL = "cabal"
    FRESH_WALLET = "fresh_wallet"


class ExitReason(Enum):
    """Reason for trade exit."""
    T1_HIT = "t1_hit"           # 2x target
    T2_HIT = "t2_hit"           # 5x target
    T3_HIT = "t3_hit"           # 10x target
    STOP_LOSS = "stop_loss"     # -30% stop
    TIME_EXIT = "time_exit"     # Max hold time
    RUG_PULL = "rug_pull"       # Token went to 0
    NO_EXIT = "no_exit"         # Still holding at end of backtest


@dataclass
class HistoricalTransaction:
    """A historical transaction from a tracked wallet."""
    tx_hash: str
    wallet_address: str
    timestamp: datetime
    token_mint: str
    token_symbol: Optional[str] = None
    action: str = "buy"  # buy or sell
    amount_sol: Decimal = Decimal("0")
    amount_tokens: Decimal = Decimal("0")
    price_per_token: Optional[Decimal] = None
    

@dataclass
class TokenPricePoint:
    """A single price point for a token."""
    timestamp: datetime
    price_usd: Decimal
    price_sol: Decimal
    volume_24h: Optional[Decimal] = None


@dataclass
class BacktestTrade:
    """A simulated trade during backtest."""
    trade_id: str
    signal_type: SignalType
    source_wallet: str
    token_mint: str
    token_symbol: Optional[str] = None
    
    # Entry
    entry_time: datetime = None
    entry_price: Decimal = Decimal("0")
    position_size_sol: Decimal = Decimal("1")
    
    # Exit
    exit_time: Optional[datetime] = None
    exit_price: Optional[Decimal] = None
    exit_reason: ExitReason = ExitReason.NO_EXIT
    
    # Performance
    pnl_sol: Optional[Decimal] = None
    pnl_pct: Optional[Decimal] = None
    max_price: Optional[Decimal] = None  # Peak price during hold
    min_price: Optional[Decimal] = None  # Lowest price during hold
    
    def calculate_pnl(self) -> None:
        """Calculate PnL based on entry and exit prices."""
        if self.exit_price and self.entry_price > 0:
            self.pnl_pct = (self.exit_price - self.entry_price) / self.entry_price
            self.pnl_sol = self.position_size_sol * self.pnl_pct


@dataclass
class BacktestConfig:
    """Configuration for backtesting."""
    # Time range
    start_date: datetime = None
    end_date: datetime = None
    days: int = 30
    
    # Position sizing
    position_size_sol: Decimal = Decimal("1.0")
    max_positions: int = 10
    
    # Exit strategy
    t1_multiplier: Decimal = Decimal("2.0")   # 2x
    t2_multiplier: Decimal = Decimal("5.0")   # 5x
    t3_multiplier: Decimal = Decimal("10.0")  # 10x
    stop_loss_pct: Decimal = Decimal("-0.30") # -30%
    max_hold_hours: int = 168  # 7 days
    
    # Filters
    min_liquidity_usd: Decimal = Decimal("10000")
    signal_types: List[SignalType] = field(default_factory=lambda: [
        SignalType.INFLUENCER, 
        SignalType.CABAL
    ])


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""
    config: BacktestConfig
    trades: List[BacktestTrade] = field(default_factory=list)
    
    # Summary metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # Performance
    win_rate: float = 0.0
    avg_pnl_pct: float = 0.0
    total_pnl_sol: Decimal = Decimal("0")
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    
    # By exit type
    t1_count: int = 0
    t2_count: int = 0
    t3_count: int = 0
    stop_loss_count: int = 0
    
    # By signal type
    influencer_trades: int = 0
    influencer_win_rate: float = 0.0
    cabal_trades: int = 0
    cabal_win_rate: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 3),
            "avg_pnl_pct": round(self.avg_pnl_pct, 3),
            "total_pnl_sol": float(self.total_pnl_sol),
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "exits": {
                "t1_2x": self.t1_count,
                "t2_5x": self.t2_count,
                "t3_10x": self.t3_count,
                "stop_loss": self.stop_loss_count,
            },
            "by_signal": {
                "influencer": {
                    "trades": self.influencer_trades,
                    "win_rate": round(self.influencer_win_rate, 3),
                },
                "cabal": {
                    "trades": self.cabal_trades,
                    "win_rate": round(self.cabal_win_rate, 3),
                },
            },
        }
