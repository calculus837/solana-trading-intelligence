#!/usr/bin/env python3
"""
Solana Intel Engine - Command Line Interface

Manual commands for system control and monitoring:
- Status: View system health and open positions
- Stats: View P&L statistics and attribution
- Panic: Emergency sell all positions
- Simulate: Test a token for honeypot
- Breaker: Circuit breaker controls

Usage:
    python cli.py status              # System status
    python cli.py stats               # P&L statistics
    python cli.py stats --source cabal  # Stats by source
    python cli.py panic               # Panic sell all
    python cli.py simulate <token>    # Simulate token
    python cli.py breaker status      # Circuit breaker status
    python cli.py breaker unlock      # Force unlock
"""

import asyncio
import argparse
import sys
import os
from decimal import Decimal
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def color(text: str, c: str) -> str:
    """Apply color to text."""
    return f"{c}{text}{Colors.ENDC}"


async def get_db_connection():
    """Get database connection pool."""
    import asyncpg
    return await asyncpg.create_pool(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "solana_intel"),
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.getenv("POSTGRES_PASSWORD", "password"),
        min_size=1,
        max_size=3,
    )


async def get_graph_connection():
    """Get Neo4j graph driver."""
    from neo4j import AsyncGraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    await driver.verify_connectivity()
    return driver


async def cmd_status(args):
    """Display system status."""
    print(color("\n===========================================", Colors.CYAN))
    print(color("  SOLANA INTEL ENGINE - SYSTEM STATUS", Colors.BOLD))
    print(color("===========================================\n", Colors.CYAN))
    
    pool = await get_db_connection()
    
    try:
        async with pool.acquire() as conn:
            # Circuit breaker status
            cb = await conn.fetchrow("SELECT * FROM circuit_breaker_state WHERE id = 1")
            
            if cb["is_locked"]:
                status = color("[LOCKED]", Colors.RED)
                reason = cb["lock_reason"] or "Unknown"
            else:
                status = color("[ACTIVE]", Colors.GREEN)
                reason = "-"
            
            print(f"  Circuit Breaker: {status}")
            if cb["is_locked"]:
                print(f"  Lock Reason:     {reason}")
                print(f"  Unlock At:       {cb['unlock_at']}")
            print()
            
            # Daily P&L
            daily_pnl = Decimal(str(cb["daily_pnl"] or 0))
            pnl_color = Colors.GREEN if daily_pnl >= 0 else Colors.RED
            print(f"  Daily P&L:       {color(f'{daily_pnl:+.4f} SOL', pnl_color)}")
            print(f"  Consecutive L:   {cb['consecutive_losses']}")
            print()
            
            # Open positions
            positions = await conn.fetch(
                "SELECT token_mint, entry_price, position_size_sol FROM trade_log WHERE status = 'open'"
            )
            
            print(f"  Open Positions:  {color(str(len(positions)), Colors.YELLOW)}")
            
            if positions:
                print()
                print("  Token                                        Entry     Size")
                print("  " + "-" * 60)
                for pos in positions:
                    token = pos["token_mint"][:20] + "..."
                    entry = f"{pos['entry_price']:.8f}" if pos['entry_price'] else "N/A"
                    size = f"{pos['position_size_sol']:.4f}" if pos['position_size_sol'] else "N/A"
                    print(f"  {token:<44} {entry:<10} {size}")
            
            # Wallet count
            wallets = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_wallets WHERE is_active = TRUE AND is_retired = FALSE"
            )
            print(f"\n  Active Sub-wallets: {wallets}")
            
    finally:
        await pool.close()
    
    print(color("\n===========================================\n", Colors.CYAN))


async def cmd_stats(args):
    """Display P&L statistics."""
    print(color("\n===========================================", Colors.CYAN))
    print(color("  SOLANA INTEL ENGINE - STATISTICS", Colors.BOLD))
    print(color("===========================================\n", Colors.CYAN))
    
    pool = await get_db_connection()
    
    try:
        async with pool.acquire() as conn:
            # Overall stats
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_trades,
                    COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                    COUNT(*) FILTER (WHERE realized_pnl <= 0 AND status != 'open') as losses,
                    COALESCE(SUM(realized_pnl), 0) as total_pnl,
                    COALESCE(AVG(pnl_percentage), 0) as avg_pnl_pct,
                    COALESCE(SUM(fees_paid), 0) as total_fees
                FROM trade_log
            """)
            
            total = stats["total_trades"]
            wins = stats["wins"]
            losses = stats["losses"]
            win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
            
            total_pnl = Decimal(str(stats["total_pnl"]))
            pnl_color = Colors.GREEN if total_pnl >= 0 else Colors.RED
            
            print(f"  Total Trades:    {total}")
            print(f"  Win/Loss:        {color(str(wins), Colors.GREEN)} / {color(str(losses), Colors.RED)}")
            print(f"  Win Rate:        {win_rate:.1f}%")
            print(f"  Total P&L:       {color(f'{total_pnl:+.4f} SOL', pnl_color)}")
            print(f"  Avg P&L:         {stats['avg_pnl_pct']:.2%}")
            print(f"  Total Fees:      {stats['total_fees']:.6f} SOL")
            
            # Stats by source if requested
            if args.source:
                print(color(f"\n  === Stats for '{args.source}' ===", Colors.YELLOW))
                source_stats = await conn.fetchrow("""
                    SELECT * FROM signal_attribution WHERE source_type = $1
                    ORDER BY total_pnl DESC LIMIT 1
                """, args.source)
                
                if source_stats:
                    print(f"  Trades:    {source_stats['total_trades']}")
                    print(f"  Win Rate:  {source_stats['win_rate']:.1%}")
                    print(f"  Total P&L: {source_stats['total_pnl']:.4f}")
                else:
                    print("  No data for this source")
            
            # Top sources
            print(color("\n  === Top Performing Sources ===", Colors.YELLOW))
            top = await conn.fetch("""
                SELECT source_id, source_type, win_rate, total_pnl, total_trades
                FROM signal_attribution
                WHERE total_trades >= 3
                ORDER BY win_rate DESC, total_pnl DESC
                LIMIT 5
            """)
            
            if top:
                print("  Source                   Type          WR      P&L       Trades")
                print("  " + "-" * 65)
                for s in top:
                    src = s["source_id"][:20] + "..." if len(s["source_id"]) > 20 else s["source_id"]
                    wr = f"{s['win_rate']:.0%}"
                    pnl = f"{s['total_pnl']:.4f}"
                    print(f"  {src:<24} {s['source_type']:<13} {wr:<7} {pnl:<10} {s['total_trades']}")
            else:
                print("  No attribution data yet")
                
    finally:
        await pool.close()
    
    print(color("\n===========================================\n", Colors.CYAN))


async def cmd_panic(args):
    """Execute panic sell of all positions."""
    print(color("\n!! WARNING: PANIC SELL INITIATED !!", Colors.RED + Colors.BOLD))
    
    if not args.confirm:
        response = input("\nThis will sell ALL open positions. Type 'CONFIRM' to proceed: ")
        if response != "CONFIRM":
            print("Aborted.")
            return
    
    pool = await get_db_connection()
    
    try:
        async with pool.acquire() as conn:
            # Get open positions
            positions = await conn.fetch(
                "SELECT trade_id, token_mint FROM trade_log WHERE status = 'open'"
            )
            
            if not positions:
                print("\nNo open positions to sell.")
                return
            
            print(f"\nMarking {len(positions)} positions for panic sell...")
            
            # Mark all as panic sold
            await conn.execute("""
                UPDATE trade_log
                SET status = 'panic_sold',
                    exit_time = NOW(),
                    exit_tier = 'PANIC'
                WHERE status = 'open'
            """)
            
            # Trigger circuit breaker lockdown
            await conn.execute("""
                UPDATE circuit_breaker_state
                SET is_locked = TRUE,
                    locked_at = NOW(),
                    lock_reason = 'Manual panic sell',
                    unlock_at = NOW() + INTERVAL '24 hours',
                    updated_at = NOW()
                WHERE id = 1
            """)
            
            print(color("\n[OK] Panic sell complete!", Colors.GREEN))
            print(f"   {len(positions)} positions marked for immediate sale")
            print("   Circuit breaker locked for 24 hours")
            
    finally:
        await pool.close()


async def cmd_simulate(args):
    """Simulate a token for honeypot detection."""
    token = args.token
    
    print(color(f"\n[*] Simulating token: {token}", Colors.CYAN))
    print("-" * 50)
    
    # Import simulator
    from logic.simulation import TokenSimulator, RiskClassification
    
    pool = await get_db_connection()
    
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # Create minimal wrappers
            class HttpWrapper:
                async def get(self, url, params=None):
                    async with session.get(url, params=params) as resp:
                        return await resp.json()
                async def post(self, url, json=None, headers=None):
                    async with session.post(url, json=json, headers=headers) as resp:
                        return await resp.json()
            
            class RpcWrapper:
                async def simulate_transaction(self, tx): return {}
                async def get_token_accounts(self, owner): return []
            
            class DbWrapper:
                def __init__(self, pool): self.pool = pool
                async def fetch(self, q, *a):
                    async with self.pool.acquire() as c:
                        return [dict(r) for r in await c.fetch(q, *a)]
                async def execute(self, q, *a):
                    async with self.pool.acquire() as c:
                        await c.execute(q, *a)
            
            simulator = TokenSimulator(
                http_client=HttpWrapper(),
                rpc_client=RpcWrapper(),
                db_client=DbWrapper(pool),
            )
            
            result = await simulator.simulate_token(token)
            
            # Display results
            if result.is_honeypot:
                status = color("[!!] HONEYPOT DETECTED", Colors.RED + Colors.BOLD)
            elif result.risk_classification == RiskClassification.SAFE:
                status = color("[OK] SAFE", Colors.GREEN)
            elif result.risk_classification == RiskClassification.CAUTION:
                status = color("[!] CAUTION", Colors.YELLOW)
            else:
                status = color("[?] UNKNOWN", Colors.CYAN)
            
            print(f"\nResult:       {status}")
            print(f"Buy Tax:      {result.buy_tax or 'N/A'}")
            print(f"Sell Tax:     {result.sell_tax or 'N/A'}")
            print(f"Sell Blocked: {result.sell_blocked}")
            
            if result.notes:
                print(f"Notes:        {result.notes}")
                
    finally:
        await pool.close()
    
    print()


async def cmd_breaker(args):
    """Circuit breaker controls."""
    pool = await get_db_connection()
    
    try:
        async with pool.acquire() as conn:
            if args.action == "status":
                cb = await conn.fetchrow("SELECT * FROM circuit_breaker_state WHERE id = 1")
                
                print(color("\n  Circuit Breaker Status", Colors.BOLD))
                print("  " + "-" * 30)
                print(f"  Locked:           {'Yes' if cb['is_locked'] else 'No'}")
                if cb["is_locked"]:
                    print(f"  Reason:           {cb['lock_reason']}")
                    print(f"  Locked At:        {cb['locked_at']}")
                    print(f"  Unlock At:        {cb['unlock_at']}")
                print(f"  Daily P&L:        {cb['daily_pnl']:.4f}")
                print(f"  Consecutive L:    {cb['consecutive_losses']}")
                print(f"  Open Positions:   {cb['open_position_count']}")
                print(f"  Max Drawdown:     {cb['max_daily_drawdown_pct']:.0%}")
                print(f"  Max Positions:    {cb['max_open_positions']}")
                print()
                
            elif args.action == "unlock":
                if not args.force:
                    response = input("Force unlock circuit breaker? Type 'YES': ")
                    if response != "YES":
                        print("Aborted.")
                        return
                
                await conn.execute("""
                    UPDATE circuit_breaker_state
                    SET is_locked = FALSE,
                        locked_at = NULL,
                        lock_reason = NULL,
                        unlock_at = NULL,
                        consecutive_losses = 0,
                        daily_pnl = 0,
                        updated_at = NOW()
                    WHERE id = 1
                """)
                
                print(color("\n[OK] Circuit breaker unlocked!", Colors.GREEN))
                print("   Daily stats reset. Trading resumed.\n")
                
            elif args.action == "reset":
                await conn.execute("""
                    UPDATE circuit_breaker_state
                    SET daily_pnl = 0,
                        consecutive_losses = 0,
                        updated_at = NOW()
                    WHERE id = 1
                """)
                print(color("\n[OK] Daily stats reset!", Colors.GREEN))
                
    finally:
        await pool.close()


async def cmd_graph_health(args):
    """Run health check on Cabal Graph (Neo4j)."""
    print(color("\n===========================================", Colors.CYAN))
    print(color("  CABAL GRAPH - HEALTH CHECK", Colors.BOLD))
    print(color("===========================================\n", Colors.CYAN))
    
    try:
        driver = await get_graph_connection()
        
        async with driver.session() as session:
            # Count nodes
            result = await session.run("MATCH (n) RETURN count(n) as count")
            total_nodes = await result.single()
            node_count = total_nodes["count"]
            
            # Count relationships
            result = await session.run("MATCH ()-[r]->() RETURN count(r) as count")
            total_rels = await result.single()
            rel_count = total_rels["count"]
            
            # Count clusters
            result = await session.run("MATCH (c:Cabal) RETURN count(c) as count")
            cluster_result = await result.single()
            cluster_count = cluster_result["count"]
            
            # Detailed Stats
            result = await session.run("""
                MATCH (n) 
                RETURN labels(n)[0] as label, count(n) as count 
                ORDER BY count DESC
            """)
            node_stats = [record.data() async for record in result]
            
            print(f"  Status:          {color('[ONLINE]', Colors.GREEN)}")
            print(f"  Total Nodes:     {node_count}")
            print(f"  Relationships:   {rel_count}")
            print(f"  Active Cabals:   {color(str(cluster_count), Colors.YELLOW if cluster_count > 0 else Colors.CYAN)}")
            
            if node_stats:
                print(color("\n  Node Distribution:", Colors.BOLD))
                for stat in node_stats:
                    label = stat['label'] if stat['label'] else 'Unlabeled'
                    print(f"  - {label:<15} {stat['count']}")
                    
            print(color("\n[OK] Graph is healthy and responsive.", Colors.GREEN))
            
    except Exception as e:
        print(f"  Status:          {color('[OFFLINE]', Colors.RED)}")
        print(f"  Error:           {str(e)}")
    finally:
        if 'driver' in locals():
            await driver.close()
    
    print(color("\n===========================================\n", Colors.CYAN))


async def cmd_forensics(args):
    """Analyze trade forensics/failures."""
    print(color("\n===========================================", Colors.CYAN))
    print(color("  TRADE FORENSICS & FAILURES", Colors.BOLD))
    print(color("===========================================\n", Colors.CYAN))
    
    pool = await get_db_connection()
    
    try:
        async with pool.acquire() as conn:
            # Fetch recent forensic logs
            logs = await conn.fetch("""
                SELECT failure_category, details, detected_at 
                FROM trade_forensics 
                ORDER BY detected_at DESC 
                LIMIT 10
            """)
            
            if not logs:
                print("  No issues detected in forensics log.")
            else:
                for log in logs:
                    ts = log['detected_at'].strftime("%H:%M:%S")
                    etype = log['failure_category']
                    details = log['details']
                    
                    # Truncate details if too long
                    detail_str = str(details)
                    if len(detail_str) > 60:
                        detail_str = detail_str[:57] + "..."
                        
                    print(f"  [{ts}] {color(etype, Colors.RED)}: {detail_str}")
            
            # Check false positives stats if we had them (future implementation)
            
    finally:
        await pool.close()
    
    print(color("\n===========================================\n", Colors.CYAN))


async def cmd_backtest(args):
    """Run strategy backtest."""
    from backtest.cli import run_backtest
    await run_backtest(args)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Solana Intel Engine CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Status command
    subparsers.add_parser("status", help="Display system status")
    
    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Display P&L statistics")
    stats_parser.add_argument("--source", help="Filter by source type")
    
    # Panic command
    panic_parser = subparsers.add_parser("panic", help="Panic sell all positions")
    panic_parser.add_argument("--confirm", action="store_true", help="Skip confirmation")
    
    # Simulate command
    sim_parser = subparsers.add_parser("simulate", help="Simulate token for honeypot")
    sim_parser.add_argument("token", help="Token mint address")
    
    # Breaker command
    breaker_parser = subparsers.add_parser("breaker", help="Circuit breaker controls")
    breaker_parser.add_argument("action", choices=["status", "unlock", "reset"])
    breaker_parser.add_argument("--force", action="store_true", help="Skip confirmation")
    
    # Graph Health command
    subparsers.add_parser("graph-health", help="Check Neo4j graph status")
    
    # Forensics command
    subparsers.add_parser("forensics", help="View trade forensics logs")
    
    # Backtest command
    backtest_parser = subparsers.add_parser("backtest", help="Run backtest simulation")
    backtest_parser.add_argument("--days", type=int, default=30, help="Days to backtest")
    backtest_parser.add_argument("--sample", action="store_true", help="Use sample wallets", default=True)
    backtest_parser.add_argument("--wallets", help="Wallet file path")
    backtest_parser.add_argument("--data-dir", help="CSV data directory")
    backtest_parser.add_argument("--position-size", type=float, default=1.0)
    backtest_parser.add_argument("--max-positions", type=int, default=10)
    backtest_parser.add_argument("--t1", type=float, default=2.0)
    backtest_parser.add_argument("--t2", type=float, default=5.0)
    backtest_parser.add_argument("--t3", type=float, default=10.0)
    backtest_parser.add_argument("--stop-loss", type=float, default=30.0)
    backtest_parser.add_argument("--output", help="Output JSON file")
    backtest_parser.add_argument("--verbose", action="store_true")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Route to command handler
    handlers = {
        "status": cmd_status,
        "stats": cmd_stats,
        "panic": cmd_panic,
        "simulate": cmd_simulate,
        "breaker": cmd_breaker,
        "graph-health": cmd_graph_health,
        "forensics": cmd_forensics,
        "backtest": cmd_backtest,
    }
    
    handler = handlers.get(args.command)
    if handler:
        asyncio.run(handler(args))


if __name__ == "__main__":
    main()
