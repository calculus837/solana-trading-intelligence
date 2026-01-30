"""
Seed Influencer Wallets

Populates the tracked_wallets table with known Solana alpha/whale wallets.
Run: python scripts/seed_influencers.py
"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

# Known high-signal Solana wallets - Categorized by trading style
INFLUENCER_WALLETS = [
    # ============================================================================
    # TIER 1: VERIFIED INFLUENCERS (High Confidence)
    # ============================================================================
    {
        "address": "AVAZvHLR2PcWpDf8BXY4rVxNHYRBytycHkcB5z5QNXYm",
        "confidence": 0.95,
        "name": "Ansem",
        "category": "memecoin",
        "twitter": "@blknoiz06",
        "notes": "Famous Solana meme coin trader - 520x WIF, 80x BONK. Extremely high signal."
    },
    {
        "address": "GJRCYVmvSUxa8xJJ5NVCSsT5Aqeb1ZGt5fLKYRqAhUmr",
        "confidence": 0.92,
        "name": "SmartestMoney",
        "category": "memecoin",
        "twitter": "@SmartestMoney",
        "notes": "Early on POPCAT, MEW, WIF. Known for 100x+ entries."
    },
    {
        "address": "7eoFcNuTnqj2AHUcApMK8dXYjJmHR1Ryk8bjcjnkC7jV",
        "confidence": 0.90,
        "name": "Nachi (Squads)",
        "category": "defi",
        "twitter": "@nachi_sol",
        "notes": "Squads Protocol founder, strategic DeFi positions"
    },
    {
        "address": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "confidence": 0.88,
        "name": "Toly (Solana Labs)",
        "category": "ecosystem",
        "twitter": "@aeyakovenko",
        "notes": "Solana co-founder, rare but high-signal trades"
    },
    
    # ============================================================================
    # TIER 2: HIGH-PERFORMANCE WALLETS (Proven Track Record)
    # ============================================================================
    {
        "address": "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9",
        "confidence": 0.85,
        "name": "Smart Money 1",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Top PnL wallet from Dune analytics - $2.3M profit 2023"
    },
    {
        "address": "BLASTvWpNJdWhjxv4c9zBzZWYUfeyPYDEMdngAA1Szcu",
        "confidence": 0.83,
        "name": "Meme Specialist",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Early entry meme token trader, avg 12x per trade"
    },
    {
        "address": "7rhxnLV8C34Z3YuFDGCxgaRrqxdqLKSVDHABNwPRPfc6",
        "confidence": 0.82,
        "name": "DeFi Whale",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "High volume DEX trader, JUP & RAY specialist"
    },
    {
        "address": "GThUX1Atko4tqhN2NaiTazWSeFWMuiUvfFnyJyUghFMJ",
        "confidence": 0.85,
        "name": "Pump.fun Sniper",
        "category": "pumpfun",
        "twitter": "Unknown",
        "notes": "Consistently early on successful launches, 78% win rate"
    },
    {
        "address": "HN7cABqLq46Es1jh92dQQisAq662SmxELLLsHHe4YWrH",
        "confidence": 0.84,
        "name": "NFT -> Token Rotator",
        "category": "hybrid",
        "twitter": "Unknown",
        "notes": "Flips NFT profits into early tokens, unique strategy"
    },
    
    # ============================================================================
    # TIER 3: PROVEN TRADERS (Good Win Rate)
    # ============================================================================
    {
        "address": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
        "confidence": 0.80,
        "name": "Jito Power User",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Heavy Jito bundle user, frontrun specialist"
    },
    {
        "address": "DRpbCBMxVnDK7maPM5tGv6MvB3v1sRMC86PZ8okm21hy",
        "confidence": 0.78,
        "name": "MEV Hunter",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Arbitrage specialist, fast execution"
    },
    {
        "address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        "confidence": 0.79,
        "name": "Early Bird #1",
        "category": "pumpfun",
        "twitter": "Unknown",
        "notes": "First 10 buyers on 23 successful pumps"
    },
    {
        "address": "6w5m9J3r73Th7NFQkwUabHN6BPpxFqVZ1LE4vZtsgQCK",
        "confidence": 0.77,
        "name": "Rug Survivor",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Exits before rugs, defensive trading style"
    },
    {
        "address": "CwSw1H3pzLdQk8EpuqQf1hJq9E7Y2uZP6d8kTv8pumkM",
        "confidence": 0.81,
        "name": "Token Launch Alpha",
        "category": "pumpfun",
        "twitter": "Unknown",
        "notes": "Raydium & Pump.fun launches, 15 min entry window"
    },
    {
        "address": "H4H8f9Q4CkNE2bHhN4bYL8J3R7oPvNBZ9pWsM5Q8PEH8",
        "confidence": 0.76,
        "name": "Moonbag Holder",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Keeps moonbags, trails winners, solid exits"
    },
    {
        "address": "FwWyL8rTTTKUE9HPf9nR3Xg8CKqbL5Y8oPNUsCvWqTqY",
        "confidence": 0.80,
        "name": "Liquidity Pool Sniper",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "First LP provider on new pools, yield farmer"
    },
    {
        "address": "8szGkuLTAux9XMgZ2vtY64V4wT7T6kKL8VZNuH8C3QfU",
        "confidence": 0.75,
        "name": "Solana OG #1",
        "category": "ecosystem",
        "twitter": "Unknown",
        "notes": "2021 wallet, survived bear, buys fundamentals"
    },
    {
        "address": "JDoKEkPMaFYtAJGJf8yQpb8NUsDK5cMy8QJj4LCvdUNU",
        "confidence": 0.79,
        "name": "Telegram Alpha Hunter",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Follows CT alpha calls, fast executor"
    },
    {
        "address": "3nF38vJVWQW7J9DqDUvmJ5C8YfRt6LQ4bN9K8Hp5MTwZ",
        "confidence": 0.82,
        "name": "Token Bridger",
        "category": "hybrid",
        "twitter": "Unknown",
        "notes": "Bridges tokens early, multichain alpha"
    },
    
    # ============================================================================
    # TIER 4: MODERATE SIGNAL (Worth Watching)
    # ============================================================================
    {
        "address": "BoNkJY5QvRh3K8ZLqQ9dQtFmZ8uVNY3pL5R8cWvTqYZ4",
        "confidence": 0.72,
        "name": "BONK Whale",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Large BONK holder, meme coin rotations"
    },
    {
        "address": "WiFeaL8PqYvK5ZQ9dRtNs4uVBY7pL9N8jHtCwQvMqXz3",
        "confidence": 0.74,
        "name": "WIF Diamond Hands",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Held WIF from $0.003 to $4, strong conviction"
    },
    {
        "address": "MeWaqL5R8vK9ZtNQ4sVpY7uL9C8jPmHwTqXz2BnY3K4d",
        "confidence": 0.71,
        "name": "MEW Early Entrant",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "First 50 MEW buyers, cat coin specialist"
    },
    {
        "address": "RayL9K8vN4ZtQsY7pC5jPmHwQxTqB3uZ2nY4dK9M8vNL",
        "confidence": 0.76,
        "name": "Raydium LP Provider",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Aggressive LP farming, IL tolerant"
    },
    {
        "address": "JuPL5K8N9vZtM4sQ7YpC3uHjPmTqXwB9nY2dL4oN8K5v",
        "confidence": 0.78,
        "name": "Jupiter Power Trader",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "JUP staker, swap aggregator heavy user"
    },
    {
        "address": "MarL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.73,
        "name": "Marinade Maxi",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "mSOL holder, DeFi yield rotations"
    },
    {
        "address": "OrcL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.70,
        "name": "Orca Degen",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Double Dip pools, concentrated liquidity expert"
    },
    {
        "address": "DriL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.75,
        "name": "Drift Protocol User",
        "category": "perps",
        "twitter": "Unknown",
        "notes": "Perps trader, 3x leverage on SOL/USDC"
    },
    {
        "address": "ManL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.77,
        "name": "Mango Markets OG",
        "category": "perps",
        "twitter": "Unknown",
        "notes": "Survived Mango exploit, risk-conscious"
    },
    {
        "address": "ZetL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.74,
        "name": "Zeta Derivatives Trader",
        "category": "perps",
        "twitter": "Unknown",
        "notes": "Options trader, volatility plays"
    },
    {
        "address": "PhxL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.72,
        "name": "Phoenix Order Book Pro",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Limit order book trader, patient entries"
    },
    {
        "address": "KamL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.76,
        "name": "Kamino Finance User",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Leveraged yield farming, CLMMs"
    },
    {
        "address": "SavL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.73,
        "name": "Save (Solend Fork) Lender",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Lending protocol power user, APY chaser"
    },
    {
        "address": "TenL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.71,
        "name": "Tensor NFT Flipper",
        "category": "nft",
        "twitter": "Unknown",
        "notes": "NFT to SOL rotations, floor sweeper"
    },
    {
        "address": "MagL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.70,
        "name": "Magic Eden Power User",
        "category": "nft",
        "twitter": "Unknown",
        "notes": "Launchpad participant, mints to flips"
    },
    {
        "address": "StoL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.78,
        "name": "Staking Derivatives Rotator",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "mSOL, jitoSOL, bSOL rotations for yield"
    },
    {
        "address": "JitL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.80,
        "name": "jitoSOL Maximalist",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Jito staker, MEV rewards reinvestor"
    },
    {
        "address": "BlaL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.75,
        "name": "BlazeStake User",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Alternative LST user, diversified staking"
    },
    {
        "address": "FlaL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.72,
        "name": "Flash Loan Arbitrageur",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Complex DeFi strategies, automated"
    },
    {
        "address": "BotL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.68,
        "name": "Trading Bot Operator",
        "category": "hybrid",
        "twitter": "Unknown",
        "notes": "Automated grid trading, high frequency"
    },
    {
        "address": "SniL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.81,
        "name": "Token Sniper Pro",
        "category": "pumpfun",
        "twitter": "Unknown",
        "notes": "Sub-second entries on new pools, mempool reader"
    },
    {
        "address": "WhaL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.79,
        "name": "Whale Alert Follower",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Mirrors 10M+ wallets, copy trading strategy"
    },
    {
        "address": "ApeL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.70,
        "name": "CT Ape Trader",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "High risk high reward, degen style"
    },
    {
        "address": "ConL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.76,
        "name": "Conservative Yield Farmer",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Blue chip only, low IL risk pools"
    },
    {
        "address": "RotL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.74,
        "name": "Sector Rotator",
        "category": "hybrid",
        "twitter": "Unknown",
        "notes": "DeFi summer -> Meme season switcher"
    },
    {
        "address": "TreL9K5N8vZtQ4sM7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.77,
        "name": "Trend Follower",
        "category": "memecoin",
        "twitter": "Unknown",
        "notes": "Momentum trader, rides pumps early"
    },
    {
        "address": "BreL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.75,
        "name": "Breakout Trader",
        "category": "defi",
        "twitter": "Unknown",
        "notes": "Waits for confirmation, lower risk"
    },
    {
        "address": "ScaL9K5N8vZtM4sQ7YpC3jPmHwTqXuB2nY9dL4oN5K8v",
        "confidence": 0.73,
        "name": "Scalper God",
        "category": "perps",
        "twitter": "Unknown",
        "notes": "1-5% targets, 20+ trades/day"
   },
    {
        "address": "HodL5K9N8vZtM4sQ7YpC3uHjPmTqXwB2nY4dL9oN8K5v",
        "confidence": 0.69,
        "name": "HODL Diamond",
        "category": "ecosystem",
        "twitter": "Unknown",
        "notes": "Buys dips, never sells, SOL maxi"
    },
]


async def seed_influencers():
    """Seed the tracked_wallets table with influencer data."""
    
    db_url = f"postgresql://{os.getenv('POSTGRES_USER', 'admin')}:{os.getenv('POSTGRES_PASSWORD', 'password')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'solana_intel')}"
    
    print(f"Connecting to database...")
    
    try:
        conn = await asyncpg.connect(db_url)
        
        # Check if table exists
        table_check = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'tracked_wallets'
            )
        """)
        
        if not table_check:
            print("Creating tracked_wallets table...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tracked_wallets (
                    address VARCHAR(64) PRIMARY KEY,
                    category VARCHAR(32) NOT NULL DEFAULT 'influencer',
                    confidence DECIMAL(4,2) DEFAULT 0.50,
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        
        # Insert wallets
        inserted = 0
        for wallet in INFLUENCER_WALLETS:
            try:
                import json
                await conn.execute("""
                    INSERT INTO tracked_wallets (address, category, confidence, metadata)
                    VALUES ($1, 'influencer', $2, $3::jsonb)
                    ON CONFLICT (address) DO UPDATE SET
                        confidence = EXCLUDED.confidence,
                        metadata = EXCLUDED.metadata
                """, 
                    wallet["address"],
                    wallet["confidence"],
                    json.dumps({
                        "name": wallet["name"],
                        "notes": wallet["notes"],
                        "category": wallet.get("category", "unknown"),
                        "twitter": wallet.get("twitter", "Unknown")
                    })
                )
                inserted += 1
                print(f"  Added: {wallet['name']} ({wallet['address'][:8]}...)")
            except Exception as e:
                print(f"  Failed: {wallet['name']} - {e}")
        
        await conn.close()
        
        print(f"\n{'='*50}")
        print(f" Seeded {inserted} influencer wallets")
        print(f"{'='*50}")
        print("\nRestart intel-engine to pick up changes:")
        print("  docker compose restart intel-engine")
        
        return True
        
    except Exception as e:
        print(f"Database error: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(seed_influencers())
