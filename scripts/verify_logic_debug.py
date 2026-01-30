
import asyncio
from decimal import Decimal
from unittest.mock import MagicMock
from logic.influencer_monitor import InfluencerMonitor
# from logic.main import LogicEngine

# Mock DB Client
class MockDB:
    async def fetch(self, query):
        print("DEBUG: MockDB fetch called")
        # Return the test wallet
        return [{
            'address': '5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1',
            'confidence': Decimal('0.9'),
            'metadata': {'name': 'Test Influencer'}
        }]

async def test_monitor_logic():
    print("--- Starting Isolation Test ---")
    
    # 1. Setup Monitor
    db = MockDB()
    monitor = InfluencerMonitor(db)
    
    # 2. Refresh Whitelist
    await monitor.refresh_whitelist()
    print(f"Monitor influencers: {monitor.influencers}")
    
    # 3. Simulate Event
    tx_data = {
        "wallet_address": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "token_in": "So11111111111111111111111111111111111111112", # SOL
        "token_out": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", # BONK
        "amount_in": 10.5,
        "amount_out": 5000000.0,
        "program_id": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
    }
    
    print(f"Processing event: {tx_data}")
    signal = await monitor.process_event(tx_data)
    
    if signal:
        print("\n✅ SIGNAL GENERATED!")
        print(f"Address: {signal.influencer_address}")
        print(f"Token: {signal.token_mint}")
        print(f"Action: {signal.action}")
        print(f"Amount In: {signal.amount_in}")
    else:
        print("\n❌ NO SIGNAL GENERATED")

if __name__ == "__main__":
    asyncio.run(test_monitor_logic())
