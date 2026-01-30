import asyncio
import asyncpg
import json
import os
import time
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from redis.asyncio import Redis
from dotenv import load_dotenv

load_dotenv()

LOG_FILE = "simulate_fresh_flow.log"

def log_to_file(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    print(msg)

async def simulate_fresh_wallet_flow():
    """
    Comprehensive simulation for Fresh Wallet Forensics alert.
    Writes to simulate_fresh_flow.log for background visibility.
    """
    
    # DB Config
    POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
    POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
    POSTGRES_DB = os.getenv('POSTGRES_DB', 'solana_intel')
    POSTGRES_USER = os.getenv('POSTGRES_USER', 'admin')
    POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'password')
    
    POSTGRES_DSN = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    
    # Redis Config
    REDIS_URL = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}"
    
    log_to_file("Connecting to Database and Redis...")
    try:
        conn = await asyncpg.connect(POSTGRES_DSN)
        redis = Redis.from_url(REDIS_URL)
    except Exception as e:
        log_to_file(f"Connection failed: {e}")
        return
    
    try:
        # 1. Setup Data
        ts = int(time.time())
        wallet_address = f"SimWallet_{ts}"[:44]
        tx_hash_onchain = f"SimSig_Onchain_{ts}"[:88]
        tx_hash_cex = f"SimSig_Cex_{ts}"[:88]
        amount = Decimal("15.5")
        
        cex_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        funding_time = cex_time + timedelta(minutes=1)
        
        log_to_file(f"Injecting DB records for wallet: {wallet_address}")
        
        # 2. Ensure wallet is tracked as fresh_wallet
        await conn.execute("""
            INSERT INTO tracked_wallets (address, category, confidence)
            VALUES ($1, 'fresh_wallet', 0.95)
            ON CONFLICT (address) DO UPDATE SET category = 'fresh_wallet'
        """, wallet_address)
        
        # 3. Insert the on-chain funding event
        await conn.execute("""
            INSERT INTO tx_events (event_time, slot, tx_hash, wallet_address, action, amount_in)
            VALUES ($1, $2, $3, $4, 'transfer', $5)
            ON CONFLICT DO NOTHING
        """, funding_time, 12345678, tx_hash_onchain, wallet_address, amount)
        
        log_to_file("Database records injected.")
        
        # 4. Publish CEX withdrawal to Redis
        payload = {
            "tx_hash": tx_hash_cex,
            "cex_source": "Binance",
            "amount": float(amount),
            "decimals": 9,
            "target_address": wallet_address,
            "recipient_tx_count": 0,
            "slot": 12345677,
            "timestamp": cex_time.isoformat()
        }
        
        log_to_file(f"Publishing matching CEX Withdrawal to Redis: {tx_hash_cex[:12]}...")
        await redis.publish("solana:cex_withdrawals", json.dumps(payload))
        
        log_to_file("\nSimulation complete!")
        log_to_file("-" * 40)
        log_to_file(f"Wallet: {wallet_address}")
        log_to_file("-" * 40)

    except Exception as e:
        log_to_file(f"Error during simulation: {e}")
    finally:
        await conn.close()
        await redis.close()

if __name__ == "__main__":
    # Clear log file before start
    with open(LOG_FILE, "w") as f:
        f.write(f"--- Simulation started at {datetime.now().isoformat()} ---\n")
    asyncio.run(simulate_fresh_wallet_flow())
