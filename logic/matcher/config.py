"""Configuration for the Fresh Wallet Matcher."""

from decimal import Decimal
from dataclasses import dataclass


@dataclass
class MatcherConfig:
    """Configuration parameters for CEX-Fresh Wallet matching."""
    
    # Time window for matching (milliseconds)
    MAX_TIME_WINDOW_MS: int = 300_000  # 5 minutes
    
    # Amount tolerance for matching (percentage as decimal)
    MAX_AMOUNT_DELTA_PCT: Decimal = Decimal("0.001")  # 0.1%
    
    # Hard limit for amount difference including gas
    MAX_AMOUNT_DELTA_HARD_PCT: Decimal = Decimal("0.005")  # 0.5%
    
    # Scoring weights
    TIME_WEIGHT: Decimal = Decimal("0.4")
    AMOUNT_WEIGHT: Decimal = Decimal("0.6")
    
    # Minimum score to consider a match valid
    MIN_MATCH_SCORE: Decimal = Decimal("0.75")
    
    # Bonus for truly fresh wallets (tx_count == 0)
    FRESHNESS_BONUS: Decimal = Decimal("0.1")
    
    # Redis TTL buffer (seconds)
    REDIS_TTL_BUFFER: int = 60
    
    # Database query limits
    MAX_CANDIDATES_PER_QUERY: int = 100


# Default configuration
DEFAULT_CONFIG = MatcherConfig()
