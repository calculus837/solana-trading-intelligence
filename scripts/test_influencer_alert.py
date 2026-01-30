"""
Influencer Alert Test

Tests the Influencer Monitor by:
1. Simulating a buy transaction from a tracked influencer wallet
2. Publishing it to Redis
3. Listening for the resulting alert

Usage:
    python scripts/test_influencer_alert.py
"""

import asyncio
import json
import redis.asyncio as redis
from datetime import datetime, timezone

REDIS_URL = "redis://localhost:6379"

# One of the wallets we seeded (Smart Money 1)
INFLUENCER_WALLET = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
# SOL Mint
SOL_MINT = "So11111111111111111111111111111111111111112"
# Target Token (BONK)
TARGET_TOKEN = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

async def listen_for_alerts(redis_client):
    """Listen for the expected alert."""
    print("Listening for alerts on 'solana:alerts'...")
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("solana:alerts")
    
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                print(f"Received Alert: {data}")
                
                if data.get("type") == "influencer" and (data.get("influencer_address") == INFLUENCER_WALLET or data.get("wallet_address") == INFLUENCER_WALLET):
                    print("\n[SUCCESS] Influencer alert received!")
                    print(f"  Wallet: {data.get('wallet')}")
                    print(f"  Token: {data.get('token')}")
                    print(f"  Action: {data.get('action')}")
                    return True
                    
    except asyncio.TimeoutError:
        print("\n[FAIL] Timeout waiting for alert")
        return False
    finally:
        await pubsub.unsubscribe("solana:alerts")

async def trigger_activity(redis_client):
    """Simulate influencer buying a token."""
    await asyncio.sleep(2)  # Wait for listener to be ready
    
    print(f"\nSimulating BUY from {INFLUENCER_WALLET[:8]}...")
    
    # Event structure matching what Ingestion publishes
    # Note: Logic engine expects generic transaction or specific event structure
    # Based on logic/main.py, it processes 'solana:transactions'
    
    tx_data = {
        "tx_hash": f"InfluencerTx_{int(datetime.now().timestamp())}",
        "slot": 123456789,
        "from_wallet": INFLUENCER_WALLET,  # The influencer
        "token_mint": TARGET_TOKEN,        # What they interaction with
        "has_swap": True,
        "token_in": SOL_MINT,             # Selling SOL
        "token_out": TARGET_TOKEN,        # Buying BONK
        "amount_in": 10.5,
        "amount_out": 5000000.0,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    await redis_client.publish("solana:transactions", json.dumps(tx_data))
    print("Transaction published!")

async def main():
    print("=" * 60)
    print("  INFLUENCER ALERT TEST")
    print("=" * 60)
    
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    
    try:
        # Run listener and trigger concurrently
        listener_task = asyncio.create_task(asyncio.wait_for(listen_for_alerts(redis_client), timeout=10))
        trigger_task = asyncio.create_task(trigger_activity(redis_client))
        
        success = await listener_task
        await trigger_task
        
    except asyncio.TimeoutError:
        print("\n[FAIL] Timed out waiting for alert.")
        success = False
    except Exception as e:
        print(f"\n[ERROR] {e}")
        success = False
    finally:
        await redis_client.aclose()
        
    if success:
        print("\nTest Passed!")
    else:
        print("\nTest Failed!")

if __name__ == "__main__":
    asyncio.run(main())
