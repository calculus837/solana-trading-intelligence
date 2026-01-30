"""CLI for running backtests."""

import asyncio
import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from .models import BacktestConfig, SignalType
from .replay_engine import ReplayEngine
from .analyzer import PerformanceAnalyzer
from .csv_loader import CSVDataLoader, create_sample_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Sample influencer addresses for testing
SAMPLE_WALLETS = [
    "8FMvCTmVEvBqmJYNxaMM2Sxdn3sBH8Wnxv9kELMx9RKs",
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjw",
]


async def run_backtest_from_csv(args: argparse.Namespace) -> None:
    """Run backtest using CSV data files."""
    
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        logger.info("Creating sample CSV file...")
        create_sample_csv(data_dir / "sample_transactions.csv")
        logger.info(f"Add your Solscan CSV exports to: {data_dir}")
        sys.exit(1)
        
    # Load transactions from CSV
    loader = CSVDataLoader(str(data_dir))
    transactions = loader.load_all()
    
    if not transactions:
        logger.error("No transactions found in CSV files")
        logger.info("Download CSV exports from Solscan.io for your target wallets")
        sys.exit(1)
        
    logger.info(f"Loaded {len(transactions)} transactions from CSV files")
    
    # Configure backtest
    config = BacktestConfig(
        days=args.days,
        position_size_sol=Decimal(str(args.position_size)),
        max_positions=args.max_positions,
        t1_multiplier=Decimal(str(args.t1)),
        t2_multiplier=Decimal(str(args.t2)),
        t3_multiplier=Decimal(str(args.t3)),
        stop_loss_pct=Decimal(str(-args.stop_loss / 100)),
    )
    
    # Run backtest with CSV transactions
    engine = ReplayEngine(config)
    result = await engine.run_backtest_from_transactions(transactions)
    
    # Analyze and report
    analyzer = PerformanceAnalyzer(result)
    analyzer.print_summary()
    
    if args.output:
        analyzer.save_report(args.output)


async def run_backtest(args: argparse.Namespace) -> None:
    """Run the backtest with given arguments."""
    
    # Check if using CSV mode
    if args.data_dir:
        await run_backtest_from_csv(args)
        return
    
    # Load wallet addresses
    if args.sample:
        wallets = SAMPLE_WALLETS
        logger.info("Using sample wallet addresses")
    elif args.wallets:
        wallets_file = Path(args.wallets)
        if not wallets_file.exists():
            logger.error(f"Wallets file not found: {args.wallets}")
            sys.exit(1)
        # Parse wallet file, stripping comments (# and everything after)
        wallets = []
        for line in wallets_file.read_text().splitlines():
            line = line.split('#')[0].strip()  # Remove comments
            if line and len(line) >= 32:  # Valid Solana address
                wallets.append(line)
    else:
        logger.error("No data source specified. Use --data-dir, --sample, or --wallets FILE")
        sys.exit(1)
        
    logger.info(f"Running backtest on {len(wallets)} wallets for {args.days} days")
    
    # Configure backtest
    config = BacktestConfig(
        days=args.days,
        position_size_sol=Decimal(str(args.position_size)),
        max_positions=args.max_positions,
        t1_multiplier=Decimal(str(args.t1)),
        t2_multiplier=Decimal(str(args.t2)),
        t3_multiplier=Decimal(str(args.t3)),
        stop_loss_pct=Decimal(str(-args.stop_loss / 100)),
    )
    
    # Map wallets to signal types (all influencer by default)
    signal_types = {addr: SignalType.INFLUENCER for addr in wallets}
    
    # Run backtest
    engine = ReplayEngine(config)
    result = await engine.run_backtest(wallets, signal_types)
    
    # Analyze and report
    analyzer = PerformanceAnalyzer(result)
    analyzer.print_summary()
    
    # Save report if output specified
    if args.output:
        analyzer.save_report(args.output)
        
    # Print best/worst trades
    if args.verbose:
        print("\nBest Trades:")
        for trade in analyzer.get_best_trades(3):
            print(f"  {trade.token_symbol or trade.token_mint[:8]}: "
                  f"{trade.pnl_pct:+.1%} ({trade.exit_reason.value})")
                  
        print("\nWorst Trades:")
        for trade in analyzer.get_worst_trades(3):
            print(f"  {trade.token_symbol or trade.token_mint[:8]}: "
                  f"{trade.pnl_pct:+.1%} ({trade.exit_reason.value})")


def main():
    parser = argparse.ArgumentParser(
        description="Backtest the Solana Intel Engine trading strategy"
    )
    
    # Data source
    parser.add_argument(
        "--data-dir",
        help="Directory containing Solscan CSV export files (offline mode)"
    )
    parser.add_argument(
        "--wallets", "-w",
        help="Path to file with wallet addresses (one per line)"
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Use sample influencer wallets for testing (requires API)"
    )
    
    # Time range
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=30,
        help="Number of days to backtest (default: 30)"
    )
    
    # Position sizing
    parser.add_argument(
        "--position-size", "-s",
        type=float,
        default=1.0,
        help="Position size in SOL (default: 1.0)"
    )
    parser.add_argument(
        "--max-positions", "-m",
        type=int,
        default=10,
        help="Maximum concurrent positions (default: 10)"
    )
    
    # Exit strategy
    parser.add_argument(
        "--t1",
        type=float,
        default=2.0,
        help="T1 exit multiplier (default: 2.0x)"
    )
    parser.add_argument(
        "--t2",
        type=float,
        default=5.0,
        help="T2 exit multiplier (default: 5.0x)"
    )
    parser.add_argument(
        "--t3",
        type=float,
        default=10.0,
        help="T3 exit multiplier (default: 10.0x)"
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=30.0,
        help="Stop loss percentage (default: 30%%)"
    )
    
    # Output
    parser.add_argument(
        "--output", "-o",
        help="Save detailed report to JSON file"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show additional details"
    )
    
    args = parser.parse_args()
    
    # Run
    asyncio.run(run_backtest(args))


if __name__ == "__main__":
    main()
