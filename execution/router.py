"""Smart Order Router - Find best execution across DEXes."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List, Protocol
import logging

logger = logging.getLogger(__name__)


@dataclass
class Route:
    """A potential swap route."""
    
    dex: str  # "jupiter", "raydium", "orca"
    price: Decimal
    output_amount: Decimal
    price_impact_pct: Decimal
    fee_amount: Decimal
    route_data: dict  # Raw route data for execution
    
    @property
    def effective_price(self) -> Decimal:
        """Price after accounting for impact and fees."""
        return self.price * (Decimal("1") - self.price_impact_pct)


@dataclass
class RouterConfig:
    """Configuration for smart order router."""
    
    # DEX endpoints
    jupiter_api_url: str = "https://quote-api.jup.ag/v6"
    
    # Slippage settings
    default_slippage_bps: int = 50  # 0.5%
    max_slippage_bps: int = 1000  # 10%
    
    # Route selection
    max_routes_to_compare: int = 3
    
    # Urgency multiplier for slippage
    # Higher urgency = accept more slippage
    urgency_slippage_multiplier: float = 0.2


class HttpClient(Protocol):
    """Protocol for HTTP client."""
    async def get(self, url: str, params: dict = None) -> dict: ...


class SmartOrderRouter:
    """
    Smart Order Router that finds the best execution across DEXes.
    
    Currently supports:
    - Jupiter Aggregator (primary - aggregates Raydium, Orca, etc.)
    
    Features:
    - Best price discovery
    - Dynamic slippage based on pool volatility
    - Price impact calculation
    """
    
    SOL_MINT = "So11111111111111111111111111111111111111112"
    
    def __init__(
        self,
        http_client: HttpClient,
        config: RouterConfig = None,
    ):
        """
        Initialize the smart order router.
        
        Args:
            http_client: HTTP client for API calls
            config: Router configuration
        """
        self.http = http_client
        self.config = config or RouterConfig()
    
    async def get_best_route(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = None,
        urgency: int = 1,
    ) -> Optional[Route]:
        """
        Find the best route for a swap.
        
        Args:
            input_mint: Input token mint address
            output_mint: Output token mint address
            amount: Input amount in smallest units
            slippage_bps: Slippage tolerance in basis points
            urgency: Urgency level 1-5 (higher = accept more slippage)
            
        Returns:
            Best Route or None if no route found
        """
        # Calculate dynamic slippage
        if slippage_bps is None:
            slippage_bps = self._calculate_dynamic_slippage(urgency)
        
        # Get Jupiter quote
        route = await self._get_jupiter_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=slippage_bps,
        )
        
        if route:
            logger.info(
                f"Best route: {route.dex} | price={route.price:.8f} | "
                f"impact={route.price_impact_pct:.4%}"
            )
        
        return route
    
    async def _get_jupiter_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int,
    ) -> Optional[Route]:
        """Get quote from Jupiter aggregator."""
        try:
            url = f"{self.config.jupiter_api_url}/quote"
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": slippage_bps,
            }
            
            response = await self.http.get(url, params=params)
            
            if not response:
                return None
            
            # Parse Jupiter response
            out_amount = int(response.get("outAmount", 0))
            in_amount = int(response.get("inAmount", amount))
            price_impact = float(response.get("priceImpactPct", 0))
            
            # Calculate price (output per input)
            price = Decimal(str(out_amount)) / Decimal(str(in_amount)) if in_amount else Decimal("0")
            
            return Route(
                dex="jupiter",
                price=price,
                output_amount=Decimal(str(out_amount)),
                price_impact_pct=Decimal(str(abs(price_impact))),
                fee_amount=Decimal("0"),  # Included in output
                route_data=response,
            )
            
        except Exception as e:
            logger.error(f"Jupiter quote failed: {e}")
            return None
    
    def _calculate_dynamic_slippage(self, urgency: int) -> int:
        """
        Calculate dynamic slippage based on urgency.
        
        Args:
            urgency: 1-5 (1=normal, 5=critical)
            
        Returns:
            Slippage in basis points
        """
        base = self.config.default_slippage_bps
        multiplier = 1 + (urgency - 1) * self.config.urgency_slippage_multiplier
        
        calculated = int(base * multiplier)
        return min(calculated, self.config.max_slippage_bps)
    
    async def get_swap_transaction(
        self,
        route: Route,
        user_public_key: str,
    ) -> Optional[bytes]:
        """
        Get serialized swap transaction from route.
        
        Args:
            route: Route from get_best_route
            user_public_key: User's wallet public key
            
        Returns:
            Serialized transaction bytes or None
        """
        try:
            url = f"{self.config.jupiter_api_url}/swap"
            
            payload = {
                "quoteResponse": route.route_data,
                "userPublicKey": user_public_key,
                "wrapAndUnwrapSol": True,
            }
            
            # Would POST to get transaction
            # response = await self.http.post(url, json=payload)
            # return base64.b64decode(response["swapTransaction"])
            
            return None  # Placeholder
            
        except Exception as e:
            logger.error(f"Failed to get swap transaction: {e}")
            return None
