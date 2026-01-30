"""
Real-Time Cabal Test

This script:
1. Subscribes to Redis to get the current live slot from Solana transactions
2. Inserts coordinated wallet data at that slot into tx_events
3. Triggers detection via Redis with matching slot numbers

Usage:
    python scripts/realtime_cabal_test.py
"""

import json
import asyncio
from datetime import datetime, timezone
import redis.asyncio as redis
import asyncpg

REDIS_URL = "redis://localhost:6379"
POSTGRES_DSN = "postgresql://admin:password@localhost:5432/solana_intel"

# Raydium AMM V4 - monitored program
TARGET_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

# Test cabal wallets (44 chars each)
CABAL_WALLETS = [
    "CabaLRealTime1Test11111111111111111111111A",
    "CabaLRealTime2Test22222222222222222222222B", 
    "CabaLRealTime3Test33333333333333333333333C",
]


async def get_current_slot(redis_client, timeout=15):
    """Subscribe to transactions and get the current slot."""
    print("[1/4] Listening for live transactions to get current slot...")
    
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("solana:transactions")
    
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                slot = data.get("slot", 0)
                if slot > 0:
                    print(f"      Got live slot: {slot}")
                    return slot
    except asyncio.TimeoutError:
        raise Exception("Timeout waiting for live transactions")
    finally:
        await pubsub.unsubscribe("solana:transactions")


async def insert_cabal_data(db_conn, base_slot):
    """Insert coordinated wallet transactions at the given slot."""
    print(f"[2/4] Inserting cabal wallets at slots {base_slot} - {base_slot + 2}...")
    
    for i, wallet in enumerate(CABAL_WALLETS):
        slot = base_slot + i
        tx_hash = f"RealTimeTest_{i}_{int(datetime.now().timestamp())}"
        
        await db_conn.execute("""
            INSERT INTO tx_events (
                wallet_address, program_id, tx_hash, slot, event_time, action
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT DO NOTHING
        """,
            wallet,
            TARGET_PROGRAM,
            tx_hash,
            slot,
            datetime.now(timezone.utc),
            "swap"
        )
        print(f"      Inserted: {wallet[:24]}... | slot {slot}")


async def trigger_detection(redis_client, base_slot):
    """Publish a transaction that will trigger the cabal correlation query."""
    print(f"[3/4] Triggering detection via Redis at slot {base_slot + 3}...")
    
    # Trigger with a wallet that will query the DB and find our inserted data
    trigger_data = {
        "tx_hash": f"TriggerTx_{int(datetime.now().timestamp())}",
        "from_wallet": "TriggerWallet111111111111111111111111111T",
        "token_mint": TARGET_PROGRAM,  # Same program for correlation
        "slot": base_slot + 3,  # Within 10-slot window of our inserts
        "has_swap": True,
        "amount": 5.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    await redis_client.publish("solana:transactions", json.dumps(trigger_data))
    print("      Trigger sent!")


async def check_results(db_conn):
    """Check if cabal groups were created."""
    print("[4/4] Checking for cabal detection results...")
    
    count = await db_conn.fetchval("SELECT COUNT(*) FROM cabal_groups")
    print(f"      Cabal groups in database: {count}")
    
    # Also check Neo4j correlations would show in logs
    events = await db_conn.fetch(
        "SELECT wallet_address, slot FROM tx_events WHERE program_id = $1 ORDER BY slot DESC LIMIT 5",
        TARGET_PROGRAM
    )
    print(f"      Recent tx_events with Raydium: {len(events)} records")
    
    return count > 0


async def main():
    print("=" * 60)
    print("  REAL-TIME CABAL DETECTION TEST")
    print("=" * 60)
    print()
    
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    db_conn = await asyncpg.connect(POSTGRES_DSN)
    
    try:
        # 1. Get current slot from live stream
        current_slot = await asyncio.wait_for(
            get_current_slot(redis_client),
            timeout=15
        )
        
        # 2. Insert coordinated wallet data at that slot
        await insert_cabal_data(db_conn, current_slot)
        
        # 3. Trigger detection
        await trigger_detection(redis_client, current_slot)
        
        # 4. Wait a moment for processing
        print()
        print("Waiting 3 seconds for processing...")
        await asyncio.sleep(3)
        
        # 5. Check results
        success = await check_results(db_conn)
        
        print()
        if success:
            print("[SUCCESS] Cabal detection triggered!")
        else:
            print("[INFO] No cabal groups yet - check server logs for CABAL DETECTED")
            print("       The correlation engine should have logged detection activity")
        
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        await redis_client.aclose()
        await db_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
