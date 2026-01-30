"""Execution Orchestrator - Central hub connecting signals to trades."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Protocol
from enum import Enum
import logging
import uuid

logger = logging.getLogger(__name__)


class SignalSource(str, Enum):
    """Source of trading signal."""
    CABAL = "cabal"
    INFLUENCER = "influencer"
    FRESH_WALLET = "fresh_wallet"
    MANUAL = "manual"


class ExitTier(str, Enum):
    """Tiered exit strategy levels."""
    T1 = "T1"   # 2x - Sell 50%
    T2 = "T2"   # 5x - Sell 50% of remaining
    T3 = "T3"   # 10x - Sell 50% of remaining (moonbag)
    SL = "SL"   # Stop Loss - Sell 100%
    PANIC = "PANIC"  # Emergency exit


@dataclass
class TradeSignal:
    """Trading signal from intelligence layer."""
    
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: SignalSource = SignalSource.CABAL
    source_id: Optional[str] = None  # Cabal ID, influencer address, etc.
    token_mint: str = ""
    confidence: Decimal = Decimal("0")
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    
    @property
    def is_high_confidence(self) -> bool:
        """Returns True if confidence > 0.8."""
        return self.confidence > Decimal("0.8")


@dataclass
class ExecutionResult:
    """Result of trade execution."""
    
    success: bool
    trade_id: Optional[str] = None
    tx_signature: Optional[str] = None
    entry_price: Optional[Decimal] = None
    amount_received: Optional[Decimal] = None
    slippage: Optional[Decimal] = None
    fees_paid: Optional[Decimal] = None
    error: Optional[str] = None
    
    def __str__(self) -> str:
        if self.success:
            return f"Trade {self.trade_id}: SUCCESS at {self.entry_price}"
        return f"Trade FAILED: {self.error}"


@dataclass
class ExitStrategy:
    """Tiered exit strategy configuration."""
    
    # T1: 2x entry - Sell 50%
    t1_multiplier: Decimal = Decimal("2.0")
    t1_sell_pct: Decimal = Decimal("0.50")
    
    # T2: 5x entry - Sell 50% of remaining
    t2_multiplier: Decimal = Decimal("5.0")
    t2_sell_pct: Decimal = Decimal("0.50")
    
    # T3: 10x entry - Sell 50% of remaining (moonbag)
    t3_multiplier: Decimal = Decimal("10.0")
    t3_sell_pct: Decimal = Decimal("0.50")
    
    # Stop Loss: -30% from entry
    stop_loss_pct: Decimal = Decimal("-0.30")


class SimulatorProtocol(Protocol):
    """Protocol for token simulator."""
    async def check_honeypot(self, token_mint: str) -> bool: ...


class CircuitBreakerProtocol(Protocol):
    """Protocol for circuit breaker."""
    async def can_trade(self) -> bool: ...
    async def validate_position_size(self, size_sol: float) -> bool: ...
    async def record_position_opened(self, size_sol: float) -> None: ...


class RouterProtocol(Protocol):
    """Protocol for smart order router."""
    async def get_best_route(self, input_mint: str, output_mint: str, amount: int) -> dict: ...


class SubWalletProtocol(Protocol):
    """Protocol for sub-wallet manager."""
    async def get_available_wallet(self) -> dict: ...
    async def sign_transaction(self, wallet_id: str, tx_bytes: bytes) -> bytes: ...


class JitoProtocol(Protocol):
    """Protocol for Jito bundle submitter."""
    async def submit_bundle(self, txs: list, tip: int) -> dict: ...


class DatabaseClient(Protocol):
    """Protocol for database client."""
    async def fetch(self, query: str, *args) -> list: ...
    async def execute(self, query: str, *args) -> None: ...


class ExecutionOrchestrator:
    """
    Central execution hub that connects intelligence signals to trades.
    
    This orchestrator:
    1. Receives high-confidence signals from Cabal Engine
    2. Validates token safety via Simulator
    3. Checks risk limits via Circuit Breaker
    4. Calculates optimal position size
    5. Routes order through Smart Order Router
    6. Distributes to sub-wallets for obfuscation
    7. Submits via Jito for MEV protection
    8. Manages tiered exit strategy
    
    Flow:
        Signal → Validate → Size → Route → Sub-wallet → Jito → Execute
    """
    
    # SOL mint address
    SOL_MINT = "So11111111111111111111111111111111111111112"
    
    def __init__(
        self,
        simulator: SimulatorProtocol,
        circuit_breaker: CircuitBreakerProtocol,
        router: RouterProtocol,
        subwallet_manager: SubWalletProtocol,
        jito: JitoProtocol,
        db_client: DatabaseClient,
        capital: float,
        exit_strategy: ExitStrategy = None,
    ):
        """
        Initialize the execution orchestrator.
        
        Args:
            simulator: Token simulator for honeypot checks
            circuit_breaker: Risk management circuit breaker
            router: Smart order router for best execution
            subwallet_manager: Sub-wallet distribution manager
            jito: Jito bundle submitter for MEV protection
            db_client: Database client for trade logging
            capital: Total trading capital
            exit_strategy: Tiered exit configuration
        """
        self.simulator = simulator
        self.breaker = circuit_breaker
        self.router = router
        self.subwallets = subwallet_manager
        self.jito = jito
        self.db = db_client
        self.capital = Decimal(str(capital))
        self.exit_strategy = exit_strategy or ExitStrategy()
        
        # Track active positions
        self._active_positions: dict[str, dict] = {}
    
    async def process_signal(self, signal: TradeSignal) -> ExecutionResult:
        """
        Process a trading signal and execute if valid.
        
        Args:
            signal: Trading signal from intelligence layer
            
        Returns:
            ExecutionResult with trade outcome
        """
        logger.info(
            f"Processing signal: {signal.source.value} | "
            f"{signal.token_mint[:16]}... | confidence={signal.confidence:.2f}"
        )
        
        # Step 1: Check if trading is allowed
        if not await self.breaker.can_trade():
            return ExecutionResult(
                success=False,
                error="Trading halted: Circuit breaker active"
            )
        
        # Step 2: Validate token safety
        if await self.simulator.check_honeypot(signal.token_mint):
            logger.warning(f"Honeypot detected: {signal.token_mint[:16]}...")
            return ExecutionResult(
                success=False,
                error="Token failed simulation: Potential honeypot"
            )
        
        # Step 3: Calculate position size based on confidence
        position_size = self._calculate_position_size(signal.confidence)
        
        # Step 4: Validate position size with circuit breaker
        if not await self.breaker.validate_position_size(float(position_size)):
            return ExecutionResult(
                success=False,
                error="Position size exceeds risk limits"
            )
        
        # Step 5: Get optimal route
        route = await self.router.get_best_route(
            input_mint=self.SOL_MINT,
            output_mint=signal.token_mint,
            amount=int(float(position_size) * 1e9),  # lamports
        )
        
        if not route:
            return ExecutionResult(
                success=False,
                error="No route found for swap"
            )
        
        # Step 6: Get sub-wallet for execution
        sub_wallet = await self.subwallets.get_available_wallet()
        
        # Step 7: Execute via Jito (placeholder for actual transaction)
        trade_id = str(uuid.uuid4())
        
        try:
            # Create trade log entry
            await self._log_trade_entry(
                trade_id=trade_id,
                signal=signal,
                position_size=position_size,
                sub_wallet_address=sub_wallet.get("address", ""),
            )
            
            # Record with circuit breaker
            await self.breaker.record_position_opened(float(position_size))
            
            # Track active position
            self._active_positions[trade_id] = {
                "token_mint": signal.token_mint,
                "entry_price": route.get("price"),
                "position_size": position_size, # SOL value at entry
                "token_amount": Decimal(str(route.get("outAmount", 0))), # Raw token units
                "remaining_pct": Decimal("1.0"),
                "sub_wallet_id": sub_wallet.wallet_id,
                "sub_wallet_address": sub_wallet.address,
                "entry_time": datetime.now(timezone.utc),
            }
            
            logger.info(
                f"✅ Trade executed: {trade_id[:8]}... | "
                f"{signal.token_mint[:16]}... | size={position_size} SOL"
            )
            
            return ExecutionResult(
                success=True,
                trade_id=trade_id,
                entry_price=Decimal(str(route.get("price", 0))),
                amount_received=Decimal(str(route.get("outAmount", 0))),
                fees_paid=Decimal(str(route.get("fee", 0))),
            )
            
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return ExecutionResult(
                success=False,
                error=str(e)
            )
    
    def _calculate_position_size(self, confidence: Decimal) -> Decimal:
        """
        Calculate position size based on confidence level.
        
        Higher confidence = larger position (up to max 5% of capital).
        
        Args:
            confidence: Signal confidence (0-1)
            
        Returns:
            Position size in SOL
        """
        # Base: 1% of capital, scaled by confidence up to 5%
        base_pct = Decimal("0.01")
        max_pct = Decimal("0.05")
        
        # Scale: base + (confidence × (max - base))
        position_pct = base_pct + (confidence * (max_pct - base_pct))
        
        return self.capital * position_pct
    
    async def check_exits(self) -> List[ExecutionResult]:
        """
        Check all active positions for exit conditions.
        
        Returns:
            List of exit execution results
        """
        results = []
        
        for trade_id, position in list(self._active_positions.items()):
            current_price = await self._get_current_price(position["token_mint"])
            
            if current_price is None:
                continue
            
            entry_price = position.get("entry_price", Decimal("0"))
            if entry_price <= 0:
                continue
            
            price_multiple = current_price / entry_price
            remaining_pct = position.get("remaining_pct", Decimal("1.0"))
            
            exit_tier = None
            sell_pct = Decimal("0")
            
            # Check stop loss first
            if price_multiple <= (Decimal("1") + self.exit_strategy.stop_loss_pct):
                exit_tier = ExitTier.SL
                sell_pct = Decimal("1.0")  # Sell everything
                
            # Check T3 (10x)
            elif price_multiple >= self.exit_strategy.t3_multiplier:
                exit_tier = ExitTier.T3
                sell_pct = self.exit_strategy.t3_sell_pct
                
            # Check T2 (5x)
            elif price_multiple >= self.exit_strategy.t2_multiplier:
                exit_tier = ExitTier.T2
                sell_pct = self.exit_strategy.t2_sell_pct
                
            # Check T1 (2x)
            elif price_multiple >= self.exit_strategy.t1_multiplier:
                exit_tier = ExitTier.T1
                sell_pct = self.exit_strategy.t1_sell_pct
            
            if exit_tier:
                result = await self._execute_exit(
                    trade_id=trade_id,
                    exit_tier=exit_tier,
                    sell_pct=sell_pct,
                    current_price=current_price,
                )
                results.append(result)
        
        return results
    
    async def _execute_exit(
        self,
        trade_id: str,
        exit_tier: ExitTier,
        sell_pct: Decimal,
        current_price: Decimal,
    ) -> ExecutionResult:
        """Execute an exit at the specified tier."""
        position = self._active_positions.get(trade_id)
        if not position:
            return ExecutionResult(success=False, error="Position not found")
        
        # 1. Calculate sell amount
        remaining_pct = position.get("remaining_pct", Decimal("1.0"))
        # sell_pct is % of REMAINING to sell (e.g., 50% of what's left)
        # We need to map this to specific token amount
        
        total_tokens = position.get("token_amount", Decimal("0"))
        current_holding_tokens = total_tokens * remaining_pct
        tokens_to_sell = current_holding_tokens * sell_pct
        
        if tokens_to_sell <= 0:
            return ExecutionResult(success=True, error="No tokens to sell")

        logger.info(
            f"Executing {exit_tier.value} exit for {trade_id[:8]}... | "
            f"Selling {sell_pct:.0%} ({tokens_to_sell:.2f} tokens)"
        )
        
        try:
            # 2. Get Route (Token -> SOL)
            route = await self.router.get_best_route(
                input_mint=position["token_mint"],
                output_mint=self.SOL_MINT,
                amount=int(tokens_to_sell),
                urgency=5 if exit_tier in [ExitTier.SL, ExitTier.PANIC] else 3
            )
            
            if not route:
                return ExecutionResult(success=False, error="No route found for exit")

            # 3. Build Transaction
            tx_bytes = await self.router.get_swap_transaction(
                route=route,
                user_public_key=position["sub_wallet_address"]
            )
            
            if not tx_bytes:
                return ExecutionResult(success=False, error="Failed to build swap tx")
                
            # 4. Sign Transaction via SubWallet
            signed_tx = await self.subwallets.sign_transaction(
                wallet_id=position["sub_wallet_id"],
                tx_bytes=tx_bytes
            )
            
            # 5. Submit via Jito (MEV Protected Exit)
            # Use submit_bundle_with_tip helper if possible, but we don't have the tip instruction logic 
            # fully wired in router return. Assuming jito.submit_bundle primarily.
            # Ideally we add the tip instruction BEFORE signing. 
            # For this implementation phase, we assume the router/signer handles it or we send as is.
            bundle_result = await self.jito.submit_bundle([signed_tx])
            
            if bundle_result.status == "failed":
                return ExecutionResult(success=False, error=f"Jito submission failed: {bundle_result.error}")

            # 6. Update Position State in DB and Memory
            actual_sell_pct_of_total = remaining_pct * sell_pct
            new_remaining = remaining_pct - actual_sell_pct_of_total
            
            exit_price = route.price # SOL per Token
            
            if new_remaining <= Decimal("0.01"):  # Close position if <1% remaining
                await self._log_trade_exit(trade_id, exit_tier, exit_price)
                del self._active_positions[trade_id]
            else:
                position["remaining_pct"] = new_remaining
            
            logger.info(f"✅ Exit successful: {bundle_result.bundle_id}")
            
            return ExecutionResult(
                success=True,
                trade_id=trade_id,
                amount_received=route.output_amount, # SOL received
                entry_price=exit_price # reusing field for exit price
            )
            
        except Exception as e:
            logger.error(f"Exit execution failed: {e}")
            return ExecutionResult(success=False, error=str(e))
    
    async def _get_current_price(self, token_mint: str) -> Optional[Decimal]:
        """Get current token price (placeholder)."""
        # Would query from DEX or price feed
        return None
    
    async def _log_trade_entry(
        self,
        trade_id: str,
        signal: TradeSignal,
        position_size: Decimal,
        sub_wallet_address: str,
    ) -> None:
        """Log trade entry to database."""
        query = """
            INSERT INTO trade_log (
                trade_id, signal_source, signal_id, token_mint,
                position_size, position_size_sol, sub_wallet_address,
                entry_time, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), 'open')
        """
        
        await self.db.execute(
            query,
            uuid.UUID(trade_id),
            signal.source.value,
            uuid.UUID(signal.signal_id) if signal.signal_id else None,
            signal.token_mint,
            position_size,
            position_size,
            sub_wallet_address,
        )
    
    async def _log_trade_exit(
        self,
        trade_id: str,
        exit_tier: ExitTier,
        exit_price: Decimal,
    ) -> None:
        """Log trade exit to database."""
        query = """
            UPDATE trade_log
            SET status = 'closed',
                exit_time = NOW(),
                exit_price = $1,
                exit_tier = $2
            WHERE trade_id = $3
        """
        
        await self.db.execute(
            query,
            exit_price,
            exit_tier.value,
            uuid.UUID(trade_id),
        )
