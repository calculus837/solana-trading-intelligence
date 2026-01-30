"""
Cabal Test Data Injector

Simulates coordinated wallet activity by publishing synthetic transaction events
to Redis. This will trigger the CabalCorrelationEngine to detect the pattern.

Usage:
    python scripts/inject_cabal_test.py
"""

import json
import time
import asyncio
from datetime import datetime, timezone
import redis.asyncio as redis


# Simulated cabal wallets (acting in coordination)
CABAL_WALLETS = [
    "CabalWallet1_Test_AAAA1111BBBB2222CCCC3333DDDD4444",
    "CabalWallet2_Test_EEEE5555FFFF6666GGGG7777HHHH8888",
    "CabalWallet3_Test_IIII9999JJJJ0000KKKK1111LLLL2222",
]

# Target contract - MUST be a monitored program for cabal detection to trigger
# Using Raydium AMM V4 since that's in MONITORED_PROGRAMS
TARGET_TOKEN = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"  # Raydium AMM V4
TARGET_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"  # Raydium

REDIS_URL = "redis://localhost:6379"


async def inject_cabal_transactions():
    """Inject coordinated transactions to simulate cabal behavior."""
    
    client = redis.from_url(REDIS_URL, decode_responses=True)
    
    print("=" * 60)
    print("  CABAL TEST DATA INJECTOR")
    print("=" * 60)
    print(f"Target Token: {TARGET_TOKEN[:16]}...")
    print(f"Cabal Wallets: {len(CABAL_WALLETS)}")
    print()
    
    base_slot = int(time.time() * 1000) % 1_000_000_000  # Pseudo slot number
    
    # Inject transactions from each cabal wallet within a tight window
    for i, wallet in enumerate(CABAL_WALLETS):
        slot = base_slot + i  # Sequential slots (within block window)
        
        tx_data = {
            "tx_hash": f"TestTx_{wallet[:8]}_{int(time.time() * 1000)}",
            "from_wallet": wallet,
            "token_mint": TARGET_TOKEN,
            "program": TARGET_PROGRAM,
            "slot": slot,
            "amount": 10.0 + i,  # Slightly different amounts
            "has_swap": True,
            "is_buy": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Publish to Redis
        await client.publish("solana:transactions", json.dumps(tx_data))
        print(f"[{i+1}/{len(CABAL_WALLETS)}] Injected: {wallet[:16]}... at slot {slot}")
        
        # Small delay to simulate real timing
        await asyncio.sleep(0.3)
    
    print()
    print("[OK] All cabal transactions injected!")
    print("   Check the dashboard for CABAL DETECTED alerts.")
    print()
    
    # Also publish a quick alert notification
    alert_data = {
        "type": "system",
        "message": f"[TEST] Injected {len(CABAL_WALLETS)} coordinated wallet transactions"
    }
    await client.publish("solana:alerts", json.dumps(alert_data))
    
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(inject_cabal_transactions())
