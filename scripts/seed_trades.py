"""
Seed Sample Trade Data

Creates sample trade history for testing analytics display.
Run: python scripts/seed_trades.py
"""

import asyncio
import asyncpg
import os
import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from dotenv import load_dotenv
load_dotenv()

# Sample token mints
TOKENS = [
    ("So11111111111111111111111111111111111111112", "SOL"),
    ("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "BONK"),
    ("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "WIF"),
    ("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "JUP"),
]

# Influencer addresses (same as seed_influencers.py)
INFLUENCERS = [
    ("AVAZvHLR2PcWpDf8BXY4rVxNHYRBytycHkcB5z5QNXYm", "Ansem"),
    ("5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9", "Smart Money 1"),
    ("GThUX1Atko4tqhN2NaiTazWSeFWMuiUvfFnyJyUghFMJ", "Pump.fun Sniper"),
]


async def seed_trades():
    """Seed the trade_log and signal_attribution tables with sample data."""
    
    db_url = f"postgresql://{os.getenv('POSTGRES_USER', 'admin')}:{os.getenv('POSTGRES_PASSWORD', 'password')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'solana_intel')}"
    
    print(f"Connecting to database...")
    
    try:
        conn = await asyncpg.connect(db_url)
        
        # Generate sample trades over the past 7 days
        now = datetime.now(timezone.utc)
        trades_created = 0
        
        for day_offset in range(7):
            day = now - timedelta(days=day_offset)
            num_trades = random.randint(3, 8)  # 3-8 trades per day
            
            for _ in range(num_trades):
                # Pick random source
                source_type = random.choice(["influencer", "cabal", "fresh_wallet"])
                
                if source_type == "influencer":
                    source_id, source_name = random.choice(INFLUENCERS)
                else:
                    source_id = str(uuid.uuid4())  # Full UUID required
                    source_name = f"{source_type.title()}_{source_id[:8]}"
                
                token_mint, token_name = random.choice(TOKENS)
                
                # Simulate trade outcome (60% win rate)
                is_win = random.random() < 0.60
                
                entry_price = Decimal(str(random.uniform(0.0001, 10.0)))
                if is_win:
                    exit_price = entry_price * Decimal(str(random.uniform(1.1, 2.5)))
                else:
                    exit_price = entry_price * Decimal(str(random.uniform(0.4, 0.95)))
                
                position_size = Decimal(str(random.uniform(0.5, 5.0)))  # SOL
                pnl = (exit_price - entry_price) * position_size
                
                entry_time = day - timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                exit_time = entry_time + timedelta(hours=random.uniform(0.5, 24))
                
                trade_id = str(uuid.uuid4())
                
                # Insert trade
                try:
                    await conn.execute("""
                        INSERT INTO trade_log (
                            trade_id, signal_source, signal_id, token_mint,
                            entry_price, exit_price, position_size, realized_pnl,
                            entry_time, exit_time, status
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'closed')
                        ON CONFLICT DO NOTHING
                    """,
                        uuid.UUID(trade_id),
                        source_type,
                        source_id,
                        token_mint,
                        float(entry_price),
                        float(exit_price),
                        float(position_size),
                        float(pnl),
                        entry_time,
                        exit_time
                    )
                    trades_created += 1
                except Exception as e:
                    print(f"  Trade insert failed: {e}")
                
                # Update signal attribution
                try:
                    await conn.execute("""
                        INSERT INTO signal_attribution (
                            source_id, source_type, source_name,
                            total_trades, winning_trades, losing_trades, total_pnl,
                            last_updated
                        ) VALUES ($1, $2, $3, 1, $4, $5, $6, NOW())
                        ON CONFLICT (source_id) DO UPDATE SET
                            total_trades = signal_attribution.total_trades + 1,
                            winning_trades = signal_attribution.winning_trades + EXCLUDED.winning_trades,
                            losing_trades = signal_attribution.losing_trades + EXCLUDED.losing_trades,
                            total_pnl = signal_attribution.total_pnl + EXCLUDED.total_pnl,
                            last_updated = NOW()
                    """,
                        source_id,
                        source_type,
                        source_name,
                        1 if is_win else 0,
                        0 if is_win else 1,
                        float(pnl)
                    )
                except Exception as e:
                    print(f"  Attribution insert failed: {e}")
        
        await conn.close()
        
        print(f"\n{'='*50}")
        print(f" Created {trades_created} sample trades over 7 days")
        print(f"{'='*50}")
        print("\nTest the analytics API:")
        print("  curl http://localhost:8000/api/analytics/summary")
        print("  curl http://localhost:8000/api/analytics/leaderboard")
        
        return True
        
    except Exception as e:
        print(f"Database error: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(seed_trades())
