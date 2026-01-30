"""
Test Helius API Key

Quick script to verify your Helius API key works before deploying.
Run: python scripts/test_helius.py
"""

import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def test_helius():
    api_key = os.getenv("HELIUS_API_KEY", "")
    
    if not api_key or api_key == "your_helius_key_here":
        print("❌ HELIUS_API_KEY not set in .env file")
        print("\nTo get a key:")
        print("1. Go to https://helius.dev")
        print("2. Sign up and create a project")
        print("3. Copy your API key to .env")
        return False
    
    print(f"🔑 Testing API key: {api_key[:8]}...{api_key[-4:]}")
    
    # Test RPC endpoint
    rpc_url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
    
    async with aiohttp.ClientSession() as session:
        try:
            # Simple getHealth check
            async with session.post(
                rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"},
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and data["result"] == "ok":
                        print("✅ Helius RPC connected successfully!")
                        print(f"   Endpoint: {rpc_url[:50]}...")
                        
                        # Get current slot for latency test
                        async with session.post(
                            rpc_url,
                            json={"jsonrpc": "2.0", "id": 1, "method": "getSlot"},
                            headers={"Content-Type": "application/json"}
                        ) as slot_resp:
                            slot_data = await slot_resp.json()
                            print(f"   Current Slot: {slot_data.get('result', 'N/A')}")
                        
                        return True
                    else:
                        print(f"⚠️ Unexpected response: {data}")
                        return False
                else:
                    print(f"❌ HTTP {resp.status}: {await resp.text()}")
                    return False
                    
        except Exception as e:
            print(f"❌ Connection error: {e}")
            return False

if __name__ == "__main__":
    result = asyncio.run(test_helius())
    if result:
        print("\n🚀 Your Helius integration is ready!")
        print("   Restart intel-engine to use Helius:")
        print("   docker compose restart intel-engine")
    else:
        print("\n❌ Helius test failed. Check your API key and try again.")
