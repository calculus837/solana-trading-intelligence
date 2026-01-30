import redis
import requests
import json
import time
import sys

# Configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
API_URL = 'http://localhost:8000'

def simulate_transactions():
    """Simulate transaction data to update latency/TPS stats."""
    print("[0/3] Simulating transactions to update latency/TPS...")
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
        
        for i in range(5):
            tx_data = {
                "channel": "solana:transactions",
                "latency_ms": 45 + (i * 5),
                "tps": 2500 + (i * 100),
                "block": 250000000 + i
            }
            r.publish('solana:transactions', json.dumps(tx_data))
            time.sleep(0.2)
        
        print("[OK] Transaction data published!")
    except Exception as e:
        print(f"[ERROR] Transaction publish failed: {e}")

def simulate_influencer_alert():
    print(f"[1/3] Simulating influencer alert to Redis ({REDIS_HOST}:{REDIS_PORT})...")
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
        
        alert_data = {
            "type": "influencer",
            "address": "HsGuijDjki48...",
            "token_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", # BONK
            "token_symbol": "BONK",
            "amount_sol": 15.5,
            "message": "Influencer HsGui... bought BONK | 15.50 SOL",
            "timestamp": time.time(),
            "confidence": 0.95
        }
        
        # Publish to 'solana:alerts' channel
        r.publish('solana:alerts', json.dumps(alert_data))
        print("[OK] Alert published! Check for 'Copy Trade' button in terminal.")
    except Exception as e:
        print(f"[ERROR] Redis Publish Failed: {e}")

def execute_test_trade():
    print(f"\n[2/3] Executing test trade via API ({API_URL})...")
    
    # Using SOL -> USDC swap for test
    payload = {
        "token_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
        "amount_sol": 0.01,
        "token_symbol": "USDC",
        "source": "simulation_test"
    }
    
    try:
        print(f"   Sending POST request to {API_URL}/api/trade/execute...")
        response = requests.post(f"{API_URL}/api/trade/execute", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            print("[OK] Trade Executed Successfully!")
            print(f"   Trade ID: {data.get('trade_id')}")
            print(f"   Tokens Received: {data.get('tokens_received')}")
            print("   -> Check 'Live Positions' panel in dashboard.")
        else:
            print(f"[ERROR] Trade Failed: {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"[ERROR] API Request Failed: {e}")
        print("   (Ensure api/server.py is running on port 8080)")

if __name__ == "__main__":
    print("--- SOLANA INTEL DASHBOARD SIMULATION ---")
    
    simulate_transactions()
    time.sleep(1)
    
    simulate_influencer_alert()
    time.sleep(2)
    
    execute_test_trade()
    print("\n-----------------------------------------")

