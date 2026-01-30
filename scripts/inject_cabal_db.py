"""
Cabal Test Data - Direct Database Injection

Injects coordinated wallet activity directly into tx_events table
to verify the cabal correlation engine works correctly.

Usage:
    python scripts/inject_cabal_db.py
"""

import asyncio
import asyncpg
from datetime import datetime, timezone

# Database connection
POSTGRES_DSN = "postgresql://admin:password@localhost:5432/solana_intel"

# Simulated cabal wallets (exactly 44 chars - Solana format)
CABAL_WALLETS = [
    "CabaLWaLLet1Test1111111111111111111111111A",
    "CabaLWaLLet2Test2222222222222222222222222B",
    "CabaLWaLLet3Test3333333333333333333333333C",
]

# Target program (Raydium AMM V4 - in MONITORED_PROGRAMS)
TARGET_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

# Base slot for correlation (all within 10-slot window)
BASE_SLOT = 999_000_001


async def inject_cabal_data():
    """Insert coordinated transactions directly into tx_events."""
    
    print("=" * 60)
    print("  CABAL TEST - DIRECT DB INJECTION")
    print("=" * 60)
    
    conn = await asyncpg.connect(POSTGRES_DSN)
    
    try:
        # Insert transactions for each cabal wallet
        for i, wallet in enumerate(CABAL_WALLETS):
            slot = BASE_SLOT + i  # Sequential slots within window
            tx_hash = f"TestCabalTx_{i}_{int(datetime.now().timestamp())}"
            
            await conn.execute("""
                INSERT INTO tx_events (
                    wallet_address, program_id, tx_hash, slot, event_time, action
                ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
                wallet,
                TARGET_PROGRAM,
                tx_hash,
                slot,
                datetime.now(timezone.utc),
                "swap"
            )
            print(f"[{i+1}/{len(CABAL_WALLETS)}] Inserted: {wallet[:20]}... | slot {slot}")
        
        print()
        print("[OK] Cabal test data inserted into tx_events!")
        print()
        
        # Verify
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM tx_events WHERE program_id = $1",
            TARGET_PROGRAM
        )
        print(f"Total tx_events with Raydium program: {count}")
        
    finally:
        await conn.close()
    
    print()
    print("Now run the injection script to trigger detection via Redis:")
    print("  python scripts/inject_cabal_test.py")


if __name__ == "__main__":
    asyncio.run(inject_cabal_data())
