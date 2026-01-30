"""Jupiter Swap Client - Interface with Jupiter v6 API for token swaps."""

import base64
import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any
import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class SwapQuote:
    """Quote response from Jupiter."""
    
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    price_impact_pct: float
    slippage_bps: int
    route_data: Dict[str, Any]  # Raw response for swap request
    
    @property
    def price(self) -> Decimal:
        """Calculate effective price (output per input)."""
        if self.in_amount <= 0:
            return Decimal("0")
        return Decimal(str(self.out_amount)) / Decimal(str(self.in_amount))


@dataclass
class SwapResult:
    """Result of a swap transaction."""
    
    success: bool
    tx_signature: Optional[str] = None
    error: Optional[str] = None
    

class JupiterClient:
    """
    Client for Jupiter Aggregator API.
    
    Provides swap quotes and transaction building for Solana token swaps.
    Requires API key from https://portal.jup.ag
    
    API Docs: https://station.jup.ag/docs/apis/swap-api
    """
    
    BASE_URL = "https://api.jup.ag/swap/v1"
    
    # Common token mints
    SOL_MINT = "So11111111111111111111111111111111111111112"
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    
    def __init__(self, session: aiohttp.ClientSession = None, api_key: str = None):
        """
        Initialize Jupiter client.
        
        Args:
            session: Optional aiohttp session (created if not provided)
            api_key: Jupiter API key (loaded from JUPITER_API_KEY env if not provided)
        """
        self._session = session
        self._owns_session = session is None
        self._api_key = api_key or os.getenv("JUPITER_API_KEY")
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers
        
    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._owns_session and self._session:
            await self._session.close()
    
    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> Optional[SwapQuote]:
        """
        Get a swap quote from Jupiter.
        
        Args:
            input_mint: Input token mint address
            output_mint: Output token mint address
            amount: Input amount in smallest units (lamports for SOL)
            slippage_bps: Slippage tolerance in basis points (50 = 0.5%)
            
        Returns:
            SwapQuote or None if no route found
        """
        try:
            url = f"{self.BASE_URL}/quote"
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": slippage_bps,
            }
            
            async with self._session.get(url, params=params, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Jupiter quote failed ({response.status}): {error_text}")
                    return None
                    
                data = await response.json()
                
            return SwapQuote(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=int(data.get("inAmount", amount)),
                out_amount=int(data.get("outAmount", 0)),
                price_impact_pct=float(data.get("priceImpactPct", 0)),
                slippage_bps=slippage_bps,
                route_data=data,
            )
            
        except Exception as e:
            logger.error(f"Jupiter quote error: {e}")
            return None
    
    async def get_swap_transaction(
        self,
        quote: SwapQuote,
        user_public_key: str,
        wrap_unwrap_sol: bool = True,
        priority_fee_lamports: int = 10000,
    ) -> Optional[bytes]:
        """
        Get a serialized swap transaction from Jupiter.
        
        Args:
            quote: Quote from get_quote()
            user_public_key: User's wallet public key (base58)
            wrap_unwrap_sol: Auto wrap/unwrap SOL
            priority_fee_lamports: Priority fee for faster inclusion
            
        Returns:
            Serialized transaction bytes or None on error
        """
        try:
            url = f"{self.BASE_URL}/swap"
            payload = {
                "quoteResponse": quote.route_data,
                "userPublicKey": user_public_key,
                "wrapAndUnwrapSol": wrap_unwrap_sol,
                "prioritizationFeeLamports": priority_fee_lamports,
                "dynamicComputeUnitLimit": True,
            }
            
            async with self._session.post(url, json=payload, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Jupiter swap failed ({response.status}): {error_text}")
                    return None
                    
                data = await response.json()
                
            # Decode base64 transaction
            swap_tx_b64 = data.get("swapTransaction")
            if not swap_tx_b64:
                logger.error("No swapTransaction in response")
                return None
                
            return base64.b64decode(swap_tx_b64)
            
        except Exception as e:
            logger.error(f"Jupiter swap tx error: {e}")
            return None
    
    async def get_token_price(
        self,
        token_mint: str,
        vs_token: str = None,
    ) -> Optional[Decimal]:
        """
        Get token price from Jupiter Price API.
        
        Args:
            token_mint: Token to price
            vs_token: Quote token (defaults to USDC)
            
        Returns:
            Price or None
        """
        try:
            vs_token = vs_token or self.USDC_MINT
            url = "https://price.jup.ag/v6/price"
            params = {
                "ids": token_mint,
                "vsToken": vs_token,
            }
            
            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    return None
                    
                data = await response.json()
                
            price_data = data.get("data", {}).get(token_mint)
            if price_data:
                return Decimal(str(price_data.get("price", 0)))
                
            return None
            
        except Exception as e:
            logger.debug(f"Jupiter price error: {e}")
            return None


async def demo_quote():
    """Quick demo of getting a quote."""
    async with JupiterClient() as client:
        # Get quote for 0.01 SOL -> USDC
        quote = await client.get_quote(
            input_mint=JupiterClient.SOL_MINT,
            output_mint=JupiterClient.USDC_MINT,
            amount=10_000_000,  # 0.01 SOL in lamports
            slippage_bps=50,
        )
        
        if quote:
            print(f"Quote: {quote.in_amount} -> {quote.out_amount}")
            print(f"Price impact: {quote.price_impact_pct:.4f}%")
        else:
            print("No quote available")


if __name__ == "__main__":
    import asyncio
    asyncio.run(demo_quote())
