"""Data models for the Pre-flight Simulation module."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from enum import Enum
from typing import Optional
import json


class RiskClassification(str, Enum):
    """Token risk classification based on simulation results."""
    
    SAFE = "safe"           # buy_tax < 5% AND sell_tax < 5%
    CAUTION = "caution"     # sell_tax 5-15%
    HIGH_RISK = "high_risk" # sell_tax 15-50%
    HONEYPOT = "honeypot"   # sell_blocked OR sell_tax > 50%
    UNKNOWN = "unknown"     # Simulation failed or incomplete


@dataclass
class SimulationConfig:
    """Configuration for token simulation."""
    
    # Test amounts (in SOL)
    test_buy_amount: Decimal = Decimal("0.01")
    
    # Tax thresholds (as decimal percentages)
    safe_tax_threshold: Decimal = Decimal("0.05")     # 5%
    caution_tax_threshold: Decimal = Decimal("0.15")  # 15%
    high_risk_threshold: Decimal = Decimal("0.50")    # 50%
    
    # Slippage tolerance for simulation
    max_slippage: Decimal = Decimal("0.10")  # 10%
    
    # Timeout for simulation (seconds)
    simulation_timeout: float = 30.0
    
    # RPC endpoint for simulation
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    
    # Jupiter API for swap quotes
    jupiter_api_url: str = "https://quote-api.jup.ag/v6"


@dataclass
class SimulationResult:
    """
    Result of a token buy/sell simulation.
    
    Based on the implementation plan's Pre-flight Simulation Flow:
    1. BUY SIMULATION - Execute swap with test amount
    2. TRANSFER SIMULATION - Attempt transfer to check if blocked
    3. SELL SIMULATION - Execute swap back to base token
    4. RISK CLASSIFICATION - Categorize based on results
    """
    
    # Token identification
    token_mint: str
    program_id: str  # DEX/AMM program used
    
    # Simulation metadata
    sim_time: datetime = field(default_factory=datetime.utcnow)
    
    # Buy simulation results
    buy_success: bool = False
    buy_expected_amount: Optional[Decimal] = None
    buy_actual_amount: Optional[Decimal] = None
    buy_tax: Optional[Decimal] = None
    buy_error: Optional[str] = None
    
    # Transfer simulation results
    transfer_success: Optional[bool] = None
    transfer_blocked: bool = False
    transfer_tax: Optional[Decimal] = None
    transfer_error: Optional[str] = None
    
    # Sell simulation results
    sell_success: Optional[bool] = None
    sell_expected_output: Optional[Decimal] = None
    sell_actual_output: Optional[Decimal] = None
    sell_tax: Optional[Decimal] = None
    sell_blocked: bool = False
    sell_error: Optional[str] = None
    max_sell_amount: Optional[Decimal] = None
    
    # Final classification
    risk_classification: RiskClassification = RiskClassification.UNKNOWN
    is_honeypot: bool = False
    notes: Optional[str] = None
    
    def __post_init__(self):
        """Calculate derived fields after initialization."""
        self._classify_risk()
    
    def _classify_risk(self) -> None:
        """
        Classify token risk based on simulation results.
        
        Classification rules from implementation plan:
        - SAFE: buy_tax < 5% AND sell_tax < 5%
        - CAUTION: sell_tax 5-15%
        - HIGH_RISK: sell_tax 15-50%
        - HONEYPOT: sell_blocked OR sell_tax > 50%
        """
        # Check for honeypot conditions
        if self.sell_blocked or (self.sell_tax and self.sell_tax > Decimal("0.50")):
            self.risk_classification = RiskClassification.HONEYPOT
            self.is_honeypot = True
            return
        
        if self.transfer_blocked:
            self.risk_classification = RiskClassification.HONEYPOT
            self.is_honeypot = True
            self.notes = "Transfer blocked"
            return
        
        # If sell simulation failed without explicit blocking, mark as unknown
        if not self.sell_success and self.sell_error:
            self.risk_classification = RiskClassification.UNKNOWN
            return
        
        # Classify based on tax levels
        buy_tax = self.buy_tax or Decimal("0")
        sell_tax = self.sell_tax or Decimal("0")
        
        if buy_tax < Decimal("0.05") and sell_tax < Decimal("0.05"):
            self.risk_classification = RiskClassification.SAFE
        elif sell_tax < Decimal("0.15"):
            self.risk_classification = RiskClassification.CAUTION
        elif sell_tax < Decimal("0.50"):
            self.risk_classification = RiskClassification.HIGH_RISK
        else:
            self.risk_classification = RiskClassification.HONEYPOT
            self.is_honeypot = True
    
    @property
    def total_tax(self) -> Decimal:
        """Total round-trip tax (buy + sell)."""
        buy = self.buy_tax or Decimal("0")
        sell = self.sell_tax or Decimal("0")
        return buy + sell
    
    @property
    def is_tradeable(self) -> bool:
        """Returns True if token can be safely traded."""
        return (
            self.risk_classification in [RiskClassification.SAFE, RiskClassification.CAUTION]
            and not self.is_honeypot
            and not self.sell_blocked
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "token_mint": self.token_mint,
            "program_id": self.program_id,
            "sim_time": self.sim_time,
            "buy_success": self.buy_success,
            "sell_success": self.sell_success,
            "buy_error": self.buy_error,
            "sell_error": self.sell_error,
            "is_honeypot": self.is_honeypot,
            "notes": self.notes,
            "buy_tax": str(self.buy_tax) if self.buy_tax else None,
            "sell_tax": str(self.sell_tax) if self.sell_tax else None,
            "risk_classification": self.risk_classification.value,
        }
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        data = self.to_dict()
        data["sim_time"] = self.sim_time.isoformat()
        return json.dumps(data)


# Default configuration
DEFAULT_CONFIG = SimulationConfig()
