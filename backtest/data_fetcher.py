"""Data Fetcher - Retrieves historical transaction and price data for backtesting."""

import os
import json
import logging
import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Dict
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from .models import HistoricalTransaction, TokenPricePoint

logger = logging.getLogger(__name__)

# API Configuration
HELIUS_API_KEY = os.getenv("SOLANA_RPC_URL", "").split("api-key=")[-1] if "api-key=" in os.getenv("SOLANA_RPC_URL", "") else ""
HELIUS_BASE_URL = "https://api.helius.xyz/v0"
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
BIRDEYE_BASE_URL = "https://public-api.birdeye.so"
DEXSCREENER_BASE_URL = "https://api.dexscreener.com/latest/dex"

# Cache directory
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


class DataFetcher:
    """Fetches historical transaction and price data for backtesting."""
    
    def __init__(self, helius_api_key: str = None, birdeye_api_key: str = None):
        """
        Initialize the data fetcher.
        
        Args:
            helius_api_key: Helius API key for transaction history
            birdeye_api_key: Birdeye API key for price history
        """
        self.helius_api_key = helius_api_key or HELIUS_API_KEY
        self.birdeye_api_key = birdeye_api_key or BIRDEYE_API_KEY
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
            
    async def fetch_wallet_history(
        self, 
        wallet_address: str, 
        days: int = 30,
        use_cache: bool = True
    ) -> List[HistoricalTransaction]:
        """
        Fetch historical transactions for a wallet.
        
        Args:
            wallet_address: Solana wallet address
            days: Number of days of history to fetch
            use_cache: Whether to use cached data
            
        Returns:
            List of HistoricalTransaction objects
        """
        cache_file = CACHE_DIR / f"wallet_{wallet_address[:8]}_{days}d.json"
        
        # Check cache
        if use_cache and cache_file.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if cache_age < timedelta(hours=24):
                logger.info(f"Using cached data for {wallet_address[:8]}...")
                with open(cache_file) as f:
                    data = json.load(f)
                    return [self._dict_to_tx(tx) for tx in data if tx]
        
        logger.info(f"Fetching history for {wallet_address[:8]}... ({days} days)")
        
        transactions = []
        before_signature = None
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        
        while True:
            # Fetch transactions from Helius
            url = f"{HELIUS_BASE_URL}/addresses/{wallet_address}/transactions"
            params = {"api-key": self.helius_api_key}
            if before_signature:
                params["before"] = before_signature
                
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"Helius API error: {resp.status}")
                        break
                    data = await resp.json()
            except Exception as e:
                logger.error(f"Failed to fetch transactions: {e}")
                break
                
            if not data:
                break
                
            for tx in data:
                parsed = self._parse_transaction(tx)
                if parsed:
                    if parsed.timestamp < cutoff_time:
                        # Reached cutoff date
                        break
                    transactions.append(parsed)
                    
            # Check if we've gone past the cutoff
            if data and transactions:
                last_tx = self._parse_transaction(data[-1])
                if last_tx and last_tx.timestamp < cutoff_time:
                    break
                before_signature = data[-1].get("signature")
            else:
                break
                
            # Rate limiting
            await asyncio.sleep(0.2)
            
        # Cache results
        if transactions:
            with open(cache_file, "w") as f:
                json.dump([self._tx_to_dict(tx) for tx in transactions], f)
                
        logger.info(f"Found {len(transactions)} transactions for {wallet_address[:8]}...")
        return transactions
    
    def _parse_transaction(self, tx: dict) -> Optional[HistoricalTransaction]:
        """Parse a Helius transaction response into HistoricalTransaction."""
        try:
            # Extract relevant fields from Helius enhanced transaction
            timestamp = datetime.fromtimestamp(tx.get("timestamp", 0), tz=timezone.utc)
            
            # Look for swap/transfer events
            token_transfers = tx.get("tokenTransfers", [])
            native_transfers = tx.get("nativeTransfers", [])
            
            if not token_transfers and not native_transfers:
                return None
                
            # Find the main token involved (excluding SOL for the action)
            token_mint = None
            amount_tokens = Decimal("0")
            action = "buy"
            
            for transfer in token_transfers:
                mint = transfer.get("mint")
                if mint and mint != "So11111111111111111111111111111111111111112":
                    token_mint = mint
                    amount_tokens = Decimal(str(transfer.get("tokenAmount", 0)))
                    # If tokens are coming IN, it's a buy; if going OUT, it's a sell
                    if transfer.get("toUserAccount") == tx.get("feePayer"):
                        action = "buy"
                    else:
                        action = "sell"
                    break
                    
            if not token_mint:
                return None
                
            # Calculate SOL amount
            amount_sol = Decimal("0")
            for transfer in native_transfers:
                amount_sol += Decimal(str(transfer.get("amount", 0))) / Decimal("1e9")
                
            return HistoricalTransaction(
                tx_hash=tx.get("signature", ""),
                wallet_address=tx.get("feePayer", ""),
                timestamp=timestamp,
                token_mint=token_mint,
                token_symbol=tx.get("tokenTransfers", [{}])[0].get("symbol"),
                action=action,
                amount_sol=abs(amount_sol),
                amount_tokens=abs(amount_tokens),
            )
        except Exception as e:
            logger.debug(f"Failed to parse transaction: {e}")
            return None
            
    def _tx_to_dict(self, tx: HistoricalTransaction) -> dict:
        """Convert HistoricalTransaction to dict for caching."""
        return {
            "tx_hash": tx.tx_hash,
            "wallet_address": tx.wallet_address,
            "timestamp": tx.timestamp.isoformat(),
            "token_mint": tx.token_mint,
            "token_symbol": tx.token_symbol,
            "action": tx.action,
            "amount_sol": str(tx.amount_sol),
            "amount_tokens": str(tx.amount_tokens),
        }
        
    def _dict_to_tx(self, data: dict) -> Optional[HistoricalTransaction]:
        """Convert cached dict back to HistoricalTransaction."""
        try:
            return HistoricalTransaction(
                tx_hash=data.get("tx_hash", ""),
                wallet_address=data.get("wallet_address", ""),
                timestamp=datetime.fromisoformat(data["timestamp"]),
                token_mint=data.get("token_mint", ""),
                token_symbol=data.get("token_symbol"),
                action=data.get("action", "buy"),
                amount_sol=Decimal(str(data.get("amount_sol", "0"))),
                amount_tokens=Decimal(str(data.get("amount_tokens", "0"))),
            )
        except Exception as e:
            logger.debug(f"Failed to deserialize cached tx: {e}")
            return None
        
    async def fetch_token_price_history(
        self,
        token_mint: str,
        start_time: datetime,
        end_time: datetime,
        use_cache: bool = True
    ) -> List[TokenPricePoint]:
        """
        Fetch historical price data for a token.
        
        Args:
            token_mint: Token mint address
            start_time: Start of time range
            end_time: End of time range
            use_cache: Whether to use cached data
            
        Returns:
            List of TokenPricePoint objects
        """
        cache_key = f"price_{token_mint[:8]}_{start_time.date()}_{end_time.date()}"
        cache_file = CACHE_DIR / f"{cache_key}.json"
        
        # Check cache
        if use_cache and cache_file.exists():
            with open(cache_file) as f:
                data = json.load(f)
                return [
                    TokenPricePoint(
                        timestamp=datetime.fromisoformat(p["timestamp"]),
                        price_usd=Decimal(str(p["price_usd"])),
                        price_sol=Decimal(str(p["price_sol"])),
                    )
                    for p in data
                ]
                
        logger.info(f"Fetching price history for {token_mint[:8]}...")
        
        prices = []
        
        # Try Birdeye first (best historical data)
        if self.birdeye_api_key:
            prices = await self._fetch_birdeye_prices(token_mint, start_time, end_time)
            
        # Fallback to DexScreener (great for memecoins)
        if not prices:
            prices = await self._fetch_dexscreener_price(token_mint)
            
        # Final fallback: Jupiter (current price only)
        if not prices:
            prices = await self._fetch_jupiter_price(token_mint)
            
        # Cache results (including empty for failed tokens to avoid re-fetching)
        with open(cache_file, "w") as f:
            json.dump([
                {
                    "timestamp": p.timestamp.isoformat(),
                    "price_usd": str(p.price_usd),
                    "price_sol": str(p.price_sol),
                }
                for p in prices
            ], f)
                
        return prices
        
    async def _fetch_birdeye_prices(
        self, 
        token_mint: str,
        start_time: datetime,
        end_time: datetime,
        max_retries: int = 3
    ) -> List[TokenPricePoint]:
        """Fetch price history from Birdeye API with rate limiting."""
        
        for attempt in range(max_retries):
            try:
                # Rate limiting delay (1 second between requests for free tier)
                await asyncio.sleep(1.0)
                
                url = f"{BIRDEYE_BASE_URL}/defi/history_price"
                headers = {"X-API-KEY": self.birdeye_api_key}
                params = {
                    "address": token_mint,
                    "address_type": "token",
                    "type": "1H",  # Hourly data
                    "time_from": int(start_time.timestamp()),
                    "time_to": int(end_time.timestamp()),
                }
                
                async with self._session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 429:
                        # Rate limited - exponential backoff
                        wait_time = (2 ** attempt) * 2  # 2, 4, 8 seconds
                        logger.warning(f"Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                    elif resp.status != 200:
                        logger.warning(f"Birdeye API error: {resp.status}")
                        return []
                    data = await resp.json()
                    
                prices = []
                for item in data.get("data", {}).get("items", []):
                    prices.append(TokenPricePoint(
                        timestamp=datetime.fromtimestamp(item["unixTime"], tz=timezone.utc),
                        price_usd=Decimal(str(item.get("value", 0))),
                        price_sol=Decimal(str(item.get("value", 0))) / Decimal("100"),  # Approximate
                    ))
                return prices
            except Exception as e:
                logger.error(f"Birdeye fetch failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    
        return []
        
    async def _fetch_dexscreener_price(self, token_mint: str) -> List[TokenPricePoint]:
        """Fetch price from DexScreener API (great for memecoins)."""
        try:
            # Rate limiting (300 req/min = 5 req/sec)
            await asyncio.sleep(0.2)
            
            url = f"{DEXSCREENER_BASE_URL}/tokens/{token_mint}"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                
            # DexScreener returns pairs for this token
            pairs = data.get("pairs", [])
            
            # Filter for Solana pairs and get the one with most liquidity
            sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
            if not sol_pairs:
                return []
                
            # Sort by liquidity and take the best pair
            sol_pairs.sort(key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0), reverse=True)
            best_pair = sol_pairs[0]
            
            price_usd = Decimal(str(best_pair.get("priceUsd", 0) or 0))
            price_native = Decimal(str(best_pair.get("priceNative", 0) or 0))
            
            if price_usd > 0:
                logger.debug(f"DexScreener price for {token_mint[:8]}: ${price_usd}")
                return [TokenPricePoint(
                    timestamp=datetime.now(timezone.utc),
                    price_usd=price_usd,
                    price_sol=price_native if price_native > 0 else price_usd / Decimal("100"),
                )]
            return []
        except Exception as e:
            logger.debug(f"DexScreener price fetch failed: {e}")
            return []
            
    async def _fetch_jupiter_price(self, token_mint: str) -> List[TokenPricePoint]:
        """Fetch current price from Jupiter (fallback, no history)."""
        try:
            url = f"https://price.jup.ag/v6/price?ids={token_mint}"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                
            price_data = data.get("data", {}).get(token_mint, {})
            if price_data:
                return [TokenPricePoint(
                    timestamp=datetime.now(timezone.utc),
                    price_usd=Decimal(str(price_data.get("price", 0))),
                    price_sol=Decimal(str(price_data.get("price", 0))) / Decimal("100"),
                )]
            return []
        except Exception as e:
            logger.error(f"Jupiter price fetch failed: {e}")
            return []
            
    async def fetch_tracked_wallets(self, db_pool) -> List[str]:
        """Fetch tracked wallet addresses from database."""
        try:
            rows = await db_pool.fetch(
                "SELECT address FROM tracked_wallets WHERE category IN ('influencer', 'cabal')"
            )
            return [row["address"] for row in rows]
        except Exception as e:
            logger.error(f"Failed to fetch tracked wallets: {e}")
            return []
