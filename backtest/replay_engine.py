"""Replay Engine - Simulates strategy execution on historical data."""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Dict, Optional
from collections import defaultdict

from .models import (
    HistoricalTransaction, 
    TokenPricePoint,
    BacktestTrade,
    BacktestConfig,
    BacktestResult,
    SignalType,
    ExitReason,
)
from .data_fetcher import DataFetcher

logger = logging.getLogger(__name__)


class ReplayEngine:
    """Replays historical transactions through the trading strategy."""
    
    def __init__(self, config: BacktestConfig = None):
        """
        Initialize the replay engine.
        
        Args:
            config: Backtest configuration
        """
        self.config = config or BacktestConfig()
        self.data_fetcher = DataFetcher()
        
        # State
        self.trades: List[BacktestTrade] = []
        self.open_positions: Dict[str, BacktestTrade] = {}  # token_mint -> trade
        self.portfolio_value = Decimal("100")  # Starting balance in SOL
        self.price_cache: Dict[str, List[TokenPricePoint]] = {}
        
    async def run_backtest(
        self,
        wallet_addresses: List[str],
        signal_types: Dict[str, SignalType] = None,
    ) -> BacktestResult:
        """
        Run a complete backtest on the given wallets.
        
        Args:
            wallet_addresses: List of wallet addresses to analyze
            signal_types: Mapping of wallet address to SignalType
            
        Returns:
            BacktestResult with all trades and metrics
        """
        logger.info(f"Starting backtest for {len(wallet_addresses)} wallets...")
        
        # Calculate date range
        end_date = self.config.end_date or datetime.now(timezone.utc)
        start_date = self.config.start_date or (end_date - timedelta(days=self.config.days))
        
        # Fetch all transactions
        all_transactions: List[HistoricalTransaction] = []
        
        async with self.data_fetcher:
            for address in wallet_addresses:
                txs = await self.data_fetcher.fetch_wallet_history(
                    address, 
                    days=self.config.days
                )
                # Filter out None values and tag with signal type
                signal_type = (signal_types or {}).get(address, SignalType.INFLUENCER)
                for tx in txs:
                    if tx is not None:
                        tx._signal_type = signal_type  # Attach signal type
                        all_transactions.append(tx)
                
        # Sort by timestamp
        all_transactions.sort(key=lambda x: x.timestamp)
        logger.info(f"Processing {len(all_transactions)} transactions...")
        
        # Process each transaction
        for tx in all_transactions:
            await self._process_transaction(tx)
            
        # Close any remaining open positions at end of backtest
        await self._close_remaining_positions(end_date)
        
        # Calculate metrics
        result = self._calculate_metrics()
        
        logger.info(f"Backtest complete: {result.total_trades} trades, "
                   f"{result.win_rate:.1%} win rate, "
                   f"{result.total_pnl_sol:.2f} SOL P&L")
        
        return result
        
    async def run_backtest_from_transactions(
        self,
        transactions: List[HistoricalTransaction],
    ) -> BacktestResult:
        """
        Run backtest from pre-loaded transactions (e.g., from CSV files).
        
        Args:
            transactions: List of HistoricalTransaction objects
            
        Returns:
            BacktestResult with all trades and metrics
        """
        logger.info(f"Starting backtest with {len(transactions)} pre-loaded transactions...")
        
        # Calculate date range from transactions
        if transactions:
            end_date = max(tx.timestamp for tx in transactions)
            start_date = min(tx.timestamp for tx in transactions)
        else:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=self.config.days)
            
        # Tag transactions with default signal type if not already tagged
        for tx in transactions:
            if not hasattr(tx, '_signal_type') or tx._signal_type is None:
                tx._signal_type = SignalType.INFLUENCER
                
        # Sort by timestamp
        transactions.sort(key=lambda x: x.timestamp)
        logger.info(f"Processing transactions from {start_date.date()} to {end_date.date()}...")
        
        # Process each transaction
        for tx in transactions:
            await self._process_transaction(tx)
            
        # Close any remaining open positions at end of backtest
        await self._close_remaining_positions(end_date)
        
        # Calculate metrics
        result = self._calculate_metrics()
        
        logger.info(f"Backtest complete: {result.total_trades} trades, "
                   f"{result.win_rate:.1%} win rate, "
                   f"{result.total_pnl_sol:.2f} SOL P&L")
        
        return result
        
    async def _process_transaction(self, tx: HistoricalTransaction) -> None:
        """Process a single transaction and decide whether to enter."""
        
        # Only process buy transactions (we follow the smart money buying)
        if tx.action != "buy":
            return
            
        # Skip if we already have a position in this token
        if tx.token_mint in self.open_positions:
            return
            
        # Skip if we've reached max positions
        if len(self.open_positions) >= self.config.max_positions:
            return
            
        # Open a new paper trade
        trade = BacktestTrade(
            trade_id=str(uuid.uuid4()),
            signal_type=getattr(tx, "_signal_type", SignalType.INFLUENCER),
            source_wallet=tx.wallet_address,
            token_mint=tx.token_mint,
            token_symbol=tx.token_symbol,
            entry_time=tx.timestamp,
            entry_price=tx.price_per_token or Decimal("0.0001"),  # Fallback price
            position_size_sol=self.config.position_size_sol,
        )
        
        # Get price history for this token
        try:
            prices = await self._get_price_history(
                tx.token_mint,
                tx.timestamp,
                tx.timestamp + timedelta(hours=self.config.max_hold_hours)
            )
            
            if prices:
                # Calculate entry price from first price point
                trade.entry_price = prices[0].price_sol if prices[0].price_sol > 0 else Decimal("0.0001")
                
                # Simulate the trade through price history
                await self._simulate_trade(trade, prices)
        except Exception as e:
            logger.debug(f"Failed to get price data for {tx.token_mint[:8]}: {e}")
            # Mark as no-exit if we can't get price data
            trade.exit_reason = ExitReason.NO_EXIT
            
        self.trades.append(trade)
        
    async def _get_price_history(
        self, 
        token_mint: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[TokenPricePoint]:
        """Get price history for a token, with caching."""
        cache_key = f"{token_mint}_{start_time.date()}"
        
        if cache_key in self.price_cache:
            return self.price_cache[cache_key]
            
        async with self.data_fetcher:
            prices = await self.data_fetcher.fetch_token_price_history(
                token_mint, start_time, end_time
            )
            
        self.price_cache[cache_key] = prices
        return prices
        
    async def _simulate_trade(
        self, 
        trade: BacktestTrade, 
        prices: List[TokenPricePoint]
    ) -> None:
        """Simulate a trade through historical prices to determine exit."""
        
        if not prices or trade.entry_price <= 0:
            trade.exit_reason = ExitReason.NO_EXIT
            return
            
        entry_price = trade.entry_price
        max_price = entry_price
        min_price = entry_price
        
        for price_point in prices:
            current_price = price_point.price_sol
            
            if current_price <= 0:
                continue
                
            # Track max/min prices
            max_price = max(max_price, current_price)
            min_price = min(min_price, current_price)
            
            # Calculate current multiplier
            multiplier = current_price / entry_price
            
            # Check exit conditions
            
            # T3 Exit (10x)
            if multiplier >= self.config.t3_multiplier:
                trade.exit_price = current_price
                trade.exit_time = price_point.timestamp
                trade.exit_reason = ExitReason.T3_HIT
                break
                
            # T2 Exit (5x)
            if multiplier >= self.config.t2_multiplier:
                trade.exit_price = current_price
                trade.exit_time = price_point.timestamp
                trade.exit_reason = ExitReason.T2_HIT
                break
                
            # T1 Exit (2x)
            if multiplier >= self.config.t1_multiplier:
                trade.exit_price = current_price
                trade.exit_time = price_point.timestamp
                trade.exit_reason = ExitReason.T1_HIT
                break
                
            # Stop Loss (-30%)
            if multiplier <= (1 + float(self.config.stop_loss_pct)):
                trade.exit_price = current_price
                trade.exit_time = price_point.timestamp
                trade.exit_reason = ExitReason.STOP_LOSS
                break
                
            # Rug pull detection (>99% drop)
            if multiplier < Decimal("0.01"):
                trade.exit_price = current_price
                trade.exit_time = price_point.timestamp
                trade.exit_reason = ExitReason.RUG_PULL
                break
                
        # Store max/min prices
        trade.max_price = max_price
        trade.min_price = min_price
        
        # If no exit triggered, mark as time exit at last price
        if trade.exit_reason == ExitReason.NO_EXIT and prices:
            trade.exit_price = prices[-1].price_sol
            trade.exit_time = prices[-1].timestamp
            trade.exit_reason = ExitReason.TIME_EXIT
            
        # Calculate PnL
        trade.calculate_pnl()
        
    async def _close_remaining_positions(self, end_date: datetime) -> None:
        """Close any positions still open at backtest end."""
        for token_mint, trade in self.open_positions.items():
            if trade.exit_reason == ExitReason.NO_EXIT:
                trade.exit_time = end_date
                trade.exit_reason = ExitReason.TIME_EXIT
                trade.calculate_pnl()
                
    def _calculate_metrics(self) -> BacktestResult:
        """Calculate performance metrics from all trades."""
        result = BacktestResult(config=self.config, trades=self.trades)
        
        if not self.trades:
            return result
            
        result.total_trades = len(self.trades)
        
        # Win/Loss counting
        wins = []
        losses = []
        
        influencer_wins = 0
        influencer_total = 0
        cabal_wins = 0
        cabal_total = 0
        
        for trade in self.trades:
            if trade.pnl_pct is not None:
                if trade.pnl_pct > 0:
                    wins.append(trade)
                    result.winning_trades += 1
                else:
                    losses.append(trade)
                    result.losing_trades += 1
                    
            # By exit type
            if trade.exit_reason == ExitReason.T1_HIT:
                result.t1_count += 1
            elif trade.exit_reason == ExitReason.T2_HIT:
                result.t2_count += 1
            elif trade.exit_reason == ExitReason.T3_HIT:
                result.t3_count += 1
            elif trade.exit_reason == ExitReason.STOP_LOSS:
                result.stop_loss_count += 1
                
            # By signal type
            if trade.signal_type == SignalType.INFLUENCER:
                influencer_total += 1
                if trade.pnl_pct and trade.pnl_pct > 0:
                    influencer_wins += 1
            elif trade.signal_type == SignalType.CABAL:
                cabal_total += 1
                if trade.pnl_pct and trade.pnl_pct > 0:
                    cabal_wins += 1
                    
        # Calculate rates
        if result.total_trades > 0:
            result.win_rate = result.winning_trades / result.total_trades
            
        if influencer_total > 0:
            result.influencer_trades = influencer_total
            result.influencer_win_rate = influencer_wins / influencer_total
            
        if cabal_total > 0:
            result.cabal_trades = cabal_total
            result.cabal_win_rate = cabal_wins / cabal_total
            
        # Calculate PnL
        pnl_values = [float(t.pnl_pct or 0) for t in self.trades]
        if pnl_values:
            result.avg_pnl_pct = sum(pnl_values) / len(pnl_values)
            result.total_pnl_sol = sum(t.pnl_sol or Decimal("0") for t in self.trades)
            
        # Calculate max drawdown
        result.max_drawdown_pct = self._calculate_max_drawdown()
        
        # Calculate Sharpe ratio
        result.sharpe_ratio = self._calculate_sharpe_ratio(pnl_values)
        
        return result
        
    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from trade PnL sequence."""
        if not self.trades:
            return 0.0
            
        cumulative = []
        running_pnl = Decimal("0")
        
        for trade in self.trades:
            running_pnl += trade.pnl_sol or Decimal("0")
            cumulative.append(float(running_pnl))
            
        if not cumulative:
            return 0.0
            
        peak = cumulative[0]
        max_dd = 0.0
        
        for value in cumulative:
            if value > peak:
                peak = value
            dd = (peak - value) / max(peak, 1)
            max_dd = max(max_dd, dd)
            
        return max_dd
        
    def _calculate_sharpe_ratio(self, pnl_values: List[float]) -> float:
        """Calculate Sharpe ratio (annualized)."""
        if len(pnl_values) < 2:
            return 0.0
            
        import statistics
        
        avg_return = statistics.mean(pnl_values)
        std_return = statistics.stdev(pnl_values)
        
        if std_return == 0:
            return 0.0
            
        # Annualize (assuming ~250 trading days)
        trades_per_day = len(pnl_values) / self.config.days
        annualization_factor = (252 * trades_per_day) ** 0.5
        
        return (avg_return / std_return) * annualization_factor
