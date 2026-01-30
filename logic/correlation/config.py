"""Configuration for the Cabal Correlation Engine."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List


@dataclass
class CorrelationConfig:
    """Configuration parameters for cabal correlation detection."""
    
    # Block/Slot window for correlation detection
    # Wallets interacting with the same contract within this window are correlated
    BLOCK_WINDOW: int = 10
    
    # Minimum wallets required to form a potential cabal cluster
    MIN_CLUSTER_SIZE: int = 2  # Lowered from 3 for testing
    
    # Time proximity weight for correlation scoring
    TIME_PROXIMITY_WEIGHT: Decimal = Decimal("0.4")
    
    # Transaction ordering pattern weight
    TX_ORDER_WEIGHT: Decimal = Decimal("0.3")
    
    # Historical co-occurrence weight
    HISTORY_WEIGHT: Decimal = Decimal("0.3")
    
    # Minimum correlation score to link wallets
    MIN_CORRELATION_SCORE: Decimal = Decimal("0.5")  # Lowered from 0.6 for testing
    
    # Confidence escalation per correlated wallet
    # new_confidence = min(1.0, old_confidence + (ESCALATION_BASE × N/10))
    ESCALATION_BASE: Decimal = Decimal("0.1")
    
    # Maximum wallets to analyze per correlation event
    MAX_WALLETS_PER_EVENT: int = 50
    
    # Shared contracts threshold for strong correlation
    SHARED_CONTRACTS_STRONG: int = 5
    
    # Programs to monitor for cabal activity (DEX routers)
    MONITORED_PROGRAMS: List[str] = field(default_factory=lambda: [
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM V4
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter Aggregator
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",   # Orca Whirlpool
    ])


# Default configuration
DEFAULT_CONFIG = CorrelationConfig()
