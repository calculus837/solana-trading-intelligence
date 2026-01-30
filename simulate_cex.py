import redis
import json
from decimal import Decimal
from datetime import datetime, timezone
import time

# Configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379

def simulate_cex_withdrawal():
    """Simulate a CEX withdrawal event published to Redis."""
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
    
    # 1. Simulate a transfer from Binance to a "fresh" wallet
    # We use a random destination to simulate a new wallet being funded
    destination = "FreshWallet" + str(int(time.time()))[:8]
    tx_hash = "SimulatedCexTx" + str(int(time.time()))[:8]
    
    payload = {
        "tx_hash": tx_hash,
        "cex_source": "Binance",
        "amount": 15.5,
        "decimals": 9,
        "target_address": destination,
        "recipient_tx_count": 0,
        "slot": 12345678,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    print(f"💰 Simulating CEX Withdrawal: Binance -> {destination} | 15.5 SOL")
    r.publish("solana:cex_withdrawals", json.dumps(payload))
    print("✅ Published to solana:cex_withdrawals")

if __name__ == "__main__":
    simulate_cex_withdrawal()
