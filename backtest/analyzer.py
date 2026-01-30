"""Performance Analyzer - Generates detailed reports from backtest results."""

import json
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any
from pathlib import Path

from .models import BacktestResult, BacktestTrade, ExitReason, SignalType


class PerformanceAnalyzer:
    """Analyzes backtest results and generates reports."""
    
    def __init__(self, result: BacktestResult):
        """
        Initialize analyzer with backtest results.
        
        Args:
            result: Completed backtest result
        """
        self.result = result
        
    def generate_summary(self) -> Dict[str, Any]:
        """Generate a summary report dictionary."""
        return self.result.to_dict()
        
    def generate_detailed_report(self) -> Dict[str, Any]:
        """Generate a detailed report with trade breakdown."""
        summary = self.generate_summary()
        
        # Add trade details
        trade_list = []
        for trade in self.result.trades:
            trade_list.append({
                "trade_id": trade.trade_id[:8],
                "signal_type": trade.signal_type.value,
                "token": trade.token_symbol or trade.token_mint[:8],
                "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
                "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                "exit_reason": trade.exit_reason.value,
                "pnl_pct": float(trade.pnl_pct) if trade.pnl_pct is not None else None,
                "pnl_sol": float(trade.pnl_sol) if trade.pnl_sol is not None else None,
            })
            
        summary["trades"] = trade_list
        return summary
        
    def print_summary(self) -> None:
        """Print a formatted summary to console."""
        r = self.result
        
        print("\n" + "=" * 60)
        print("               BACKTEST RESULTS")
        print("=" * 60)
        
        print(f"\n  Total Trades:      {r.total_trades}")
        print(f"  Winning Trades:    {r.winning_trades} ({r.win_rate:.1%})")
        print(f"  Losing Trades:     {r.losing_trades}")
        
        print(f"\n  Average PnL:       {r.avg_pnl_pct:+.1%}")
        print(f"  Total PnL:         {r.total_pnl_sol:+.2f} SOL")
        print(f"  Max Drawdown:      {r.max_drawdown_pct:.1%}")
        print(f"  Sharpe Ratio:      {r.sharpe_ratio:.2f}")
        
        print("\n  Exit Breakdown:")
        print(f"    T1 (2x):         {r.t1_count}")
        print(f"    T2 (5x):         {r.t2_count}")
        print(f"    T3 (10x):        {r.t3_count}")
        print(f"    Stop Loss:       {r.stop_loss_count}")
        
        print("\n  By Signal Type:")
        print(f"    Influencer:      {r.influencer_trades} trades, {r.influencer_win_rate:.1%} win rate")
        print(f"    Cabal:           {r.cabal_trades} trades, {r.cabal_win_rate:.1%} win rate")
        
        print("\n" + "=" * 60)
        
    def save_report(self, output_path: str) -> None:
        """Save detailed report to JSON file."""
        report = self.generate_detailed_report()
        
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
            
        print(f"Report saved to: {output_path}")
        
    def get_best_trades(self, n: int = 5) -> List[BacktestTrade]:
        """Get the top N best performing trades."""
        sorted_trades = sorted(
            [t for t in self.result.trades if t.pnl_pct is not None],
            key=lambda t: t.pnl_pct,
            reverse=True
        )
        return sorted_trades[:n]
        
    def get_worst_trades(self, n: int = 5) -> List[BacktestTrade]:
        """Get the top N worst performing trades."""
        sorted_trades = sorted(
            [t for t in self.result.trades if t.pnl_pct is not None],
            key=lambda t: t.pnl_pct
        )
        return sorted_trades[:n]
        
    def get_signal_analysis(self) -> Dict[str, Any]:
        """Analyze performance by signal type."""
        analysis = {}
        
        for signal_type in SignalType:
            trades = [t for t in self.result.trades if t.signal_type == signal_type]
            if not trades:
                continue
                
            wins = [t for t in trades if t.pnl_pct and t.pnl_pct > 0]
            pnl_values = [float(t.pnl_pct) for t in trades if t.pnl_pct is not None]
            
            analysis[signal_type.value] = {
                "total_trades": len(trades),
                "winning_trades": len(wins),
                "win_rate": len(wins) / len(trades) if trades else 0,
                "avg_pnl": sum(pnl_values) / len(pnl_values) if pnl_values else 0,
            }
            
        return analysis
