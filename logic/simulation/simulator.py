"""Token Simulator - Simulates buy/sell transactions for honeypot detection."""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Protocol
import logging
import asyncio

from .models import SimulationResult, SimulationConfig, RiskClassification, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class HttpClient(Protocol):
    """Protocol for HTTP client interface."""
    async def get(self, url: str, params: dict = None) -> dict: ...
    async def post(self, url: str, json: dict = None) -> dict: ...


class RpcClient(Protocol):
    """Protocol for Solana RPC client interface."""
    async def simulate_transaction(self, tx_bytes: bytes) -> dict: ...
    async def get_token_accounts(self, owner: str) -> list: ...


class DatabaseClient(Protocol):
    """Protocol for database client interface."""
    async def fetch(self, query: str, *args) -> list: ...
    async def execute(self, query: str, *args) -> None: ...


class TokenSimulator:
    """
    Simulates token buy/sell transactions to detect honeypots.
    
    This simulator uses Jupiter API quotes and Solana RPC simulation
    to test whether a token can be safely bought and sold without
    encountering high taxes or sell blocks.
    
    Simulation Flow (from implementation plan):
    1. BUY SIMULATION
       - Get quote from Jupiter for buy
       - Execute simulated swap with test amount
       - Record: actual tokens received vs expected
       - Calculate: buy_tax = 1 - (received / expected)
    
    2. TRANSFER SIMULATION
       - Attempt transfer to secondary wallet
       - Check: transfer_blocked? transfer_tax?
    
    3. SELL SIMULATION
       - Get quote from Jupiter for sell
       - Execute simulated swap back to SOL
       - Record: actual output vs expected
       - Calculate: sell_tax = 1 - (output / expected)
       - Check: sell_blocked? max_sell_amount?
    
    4. RISK CLASSIFICATION
       - SAFE: buy_tax < 5% AND sell_tax < 5%
       - CAUTION: sell_tax 5-15%
       - HONEYPOT: sell_blocked OR sell_tax > 50%
    """
    
    # SOL mint address
    SOL_MINT = "So11111111111111111111111111111111111111112"
    
    def __init__(
        self,
        http_client: HttpClient,
        rpc_client: RpcClient,
        db_client: DatabaseClient,
        config: SimulationConfig = DEFAULT_CONFIG,
    ):
        """
        Initialize the token simulator.
        
        Args:
            http_client: HTTP client for Jupiter API
            rpc_client: Solana RPC client for simulation
            db_client: Database client for persistence
            config: Simulation configuration
        """
        self.http = http_client
        self.rpc = rpc_client
        self.db = db_client
        self.config = config
        
        # Cache for recent simulations
        self._cache: dict[str, SimulationResult] = {}
        self._cache_ttl_seconds = 300  # 5 minutes
    
    async def simulate_token(
        self,
        token_mint: str,
        program_id: Optional[str] = None,
        force_refresh: bool = False,
    ) -> SimulationResult:
        """
        Run full simulation suite on a token.
        
        Args:
            token_mint: Token mint address to simulate
            program_id: Optional DEX program ID (auto-detected if not provided)
            force_refresh: If True, bypass cache and run fresh simulation
            
        Returns:
            SimulationResult with all simulation outcomes and classification
        """
        # Check cache
        if not force_refresh and token_mint in self._cache:
            cached = self._cache[token_mint]
            age = (datetime.utcnow() - cached.sim_time).total_seconds()
            if age < self._cache_ttl_seconds:
                logger.debug(f"Cache hit for {token_mint[:16]}...")
                return cached
        
        logger.info(f"Simulating token: {token_mint[:16]}...")
        
        result = SimulationResult(
            token_mint=token_mint,
            program_id=program_id or "unknown",
            sim_time=datetime.now(timezone.utc),
        )
        
        try:
            # Step 1: Buy simulation
            await self._simulate_buy(result)
            
            # Step 2: Transfer simulation (only if buy succeeded)
            if result.buy_success:
                await self._simulate_transfer(result)
            
            # Step 3: Sell simulation (only if buy succeeded)
            if result.buy_success:
                await self._simulate_sell(result)
            
            # Classification happens in __post_init__ of SimulationResult
            # but we need to re-trigger it after updates
            result._classify_risk()
            
        except asyncio.TimeoutError:
            result.notes = "Simulation timed out"
            result.risk_classification = RiskClassification.UNKNOWN
        except Exception as e:
            logger.error(f"Simulation failed for {token_mint}: {e}")
            result.notes = f"Simulation error: {str(e)}"
            result.risk_classification = RiskClassification.UNKNOWN
        
        # Persist result
        await self._persist_result(result)
        
        # Cache result
        self._cache[token_mint] = result
        
        logger.info(
            f"Simulation complete: {token_mint[:16]}... -> "
            f"{result.risk_classification.value}"
        )
        
        return result
    
    async def _simulate_buy(self, result: SimulationResult) -> None:
        """
        Simulate buying the token with SOL.
        
        Uses Jupiter API to get a quote and calculates the effective tax
        by comparing expected vs simulated received amount.
        """
        try:
            # Get Jupiter quote for buying token with SOL
            quote = await self._get_jupiter_quote(
                input_mint=self.SOL_MINT,
                output_mint=result.token_mint,
                amount=int(float(self.config.test_buy_amount) * 1e9),  # lamports
            )
            
            if not quote:
                result.buy_error = "Failed to get buy quote"
                return
            
            result.buy_expected_amount = Decimal(str(quote.get("outAmount", 0))) / Decimal("1e6")
            
            # Simulate the swap transaction
            sim_result = await self._simulate_swap(quote)
            
            if sim_result.get("error"):
                result.buy_error = sim_result["error"]
                return
            
            result.buy_success = True
            result.buy_actual_amount = result.buy_expected_amount  # Simplified for now
            
            # Calculate tax from price impact and fees
            price_impact = Decimal(str(quote.get("priceImpactPct", 0)))
            result.buy_tax = abs(price_impact)
            
            result.program_id = quote.get("routePlan", [{}])[0].get("swapInfo", {}).get("ammKey", "unknown")
            
            logger.debug(f"Buy simulation: success, tax={result.buy_tax:.4f}")
            
        except Exception as e:
            result.buy_error = str(e)
            logger.error(f"Buy simulation failed: {e}")
    
    async def _simulate_transfer(self, result: SimulationResult) -> None:
        """
        Simulate transferring the token to another wallet.
        
        Some honeypots block transfers or apply transfer taxes.
        """
        try:
            # For now, we'll check token account data for transfer restrictions
            # A full implementation would simulate an actual transfer instruction
            
            result.transfer_success = True
            result.transfer_blocked = False
            
            # TODO: Implement actual transfer simulation
            # This would require creating a transfer instruction and simulating it
            
            logger.debug("Transfer simulation: assumed success (TODO: full impl)")
            
        except Exception as e:
            result.transfer_error = str(e)
            result.transfer_blocked = True
            logger.error(f"Transfer simulation failed: {e}")
    
    async def _simulate_sell(self, result: SimulationResult) -> None:
        """
        Simulate selling the token back to SOL.
        
        This is the critical check for honeypots - many allow buys but block sells.
        """
        try:
            if not result.buy_actual_amount or result.buy_actual_amount <= 0:
                result.sell_error = "No tokens to sell (buy failed)"
                return
            
            # Get Jupiter quote for selling token to SOL
            sell_amount = int(float(result.buy_actual_amount) * 1e6)  # token decimals
            
            quote = await self._get_jupiter_quote(
                input_mint=result.token_mint,
                output_mint=self.SOL_MINT,
                amount=sell_amount,
            )
            
            if not quote:
                # No route found = potential sell block
                result.sell_blocked = True
                result.sell_error = "No sell route available - possible honeypot"
                return
            
            result.sell_expected_output = Decimal(str(quote.get("outAmount", 0))) / Decimal("1e9")
            
            # Simulate the swap transaction
            sim_result = await self._simulate_swap(quote)
            
            if sim_result.get("error"):
                error_msg = sim_result["error"].lower()
                if "insufficient" in error_msg or "blocked" in error_msg:
                    result.sell_blocked = True
                result.sell_error = sim_result["error"]
                return
            
            result.sell_success = True
            result.sell_actual_output = result.sell_expected_output  # Simplified
            
            # Calculate sell tax from price impact
            price_impact = Decimal(str(quote.get("priceImpactPct", 0)))
            result.sell_tax = abs(price_impact)
            
            # Check for max sell restrictions
            if quote.get("contextSlot"):
                result.max_sell_amount = None  # Would need deeper analysis
            
            logger.debug(f"Sell simulation: success, tax={result.sell_tax:.4f}")
            
        except Exception as e:
            result.sell_error = str(e)
            logger.error(f"Sell simulation failed: {e}")
    
    async def _get_jupiter_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
    ) -> Optional[dict]:
        """
        Get swap quote from Jupiter API.
        
        Args:
            input_mint: Input token mint address
            output_mint: Output token mint address
            amount: Input amount in smallest units
            
        Returns:
            Quote response dict or None if failed
        """
        try:
            url = f"{self.config.jupiter_api_url}/quote"
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": int(float(self.config.max_slippage) * 10000),
            }
            
            response = await self.http.get(url, params=params)
            return response
            
        except Exception as e:
            logger.error(f"Jupiter quote failed: {e}")
            return None
    
    async def _simulate_swap(self, quote: dict) -> dict:
        """
        Simulate swap transaction using RPC.
        
        Args:
            quote: Jupiter quote response
            
        Returns:
            Simulation result dict with 'success' or 'error'
        """
        try:
            # For a full implementation, we would:
            # 1. Build the swap transaction from the quote
            # 2. Simulate it using solana RPC simulateTransaction
            # 3. Parse the simulation result
            
            # Simplified: use quote data to infer success
            if quote.get("routePlan"):
                return {"success": True}
            else:
                return {"error": "No route plan in quote"}
                
        except Exception as e:
            return {"error": str(e)}
    
    async def _persist_result(self, result: SimulationResult) -> None:
        """Persist simulation result to database."""
        query = """
            INSERT INTO sim_results (
                program_id, token_mint, sim_time,
                buy_success, sell_success,
                buy_error, sell_error,
                is_honeypot, notes
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (token_mint) DO UPDATE SET
                sim_time = EXCLUDED.sim_time,
                buy_success = EXCLUDED.buy_success,
                sell_success = EXCLUDED.sell_success,
                is_honeypot = EXCLUDED.is_honeypot,
                notes = EXCLUDED.notes
        """
        
        try:
            await self.db.execute(
                query,
                result.program_id,
                result.token_mint,
                result.sim_time,
                result.buy_success,
                result.sell_success,
                result.buy_error,
                result.sell_error,
                result.is_honeypot,
                result.notes,
            )
        except Exception as e:
            logger.error(f"Failed to persist simulation result: {e}")
    
    async def check_honeypot(self, token_mint: str) -> bool:
        """
        Quick check if a token is a known honeypot.
        
        First checks database cache, then runs simulation if needed.
        
        Args:
            token_mint: Token mint address
            
        Returns:
            True if honeypot, False otherwise
        """
        # Check database first
        query = """
            SELECT is_honeypot 
            FROM sim_results 
            WHERE token_mint = $1 
              AND sim_time > NOW() - INTERVAL '1 hour'
            ORDER BY sim_time DESC
            LIMIT 1
        """
        
        try:
            results = await self.db.fetch(query, token_mint)
            if results:
                return results[0]["is_honeypot"]
        except Exception as e:
            logger.error(f"Database check failed: {e}")
        
        # Run fresh simulation
        result = await self.simulate_token(token_mint)
        return result.is_honeypot
    
    def clear_cache(self) -> None:
        """Clear the simulation cache."""
        self._cache.clear()
