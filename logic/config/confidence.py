"""
Confidence Threshold Configuration

Per-strategy confidence thresholds to improve signal quality and reduce false positives.
Each signal type has different risk profiles and requires different minimum confidence levels.
"""

from decimal import Decimal
from typing import Dict
from enum import Enum


class SignalType(str, Enum):
    """Types of trading signals the system generates."""
    INFLUENCER = "influencer"  # Tracked wallet activity
    CABAL = "cabal"  # Cluster correlation patterns
    FRESH_WALLET = "fresh_wallet"  # CEX withdrawal forensics
    PERPS = "perps"  # Derivatives market signals
    HYBRID = "hybrid"  # Multi-signal confirmation


class RiskProfile(str, Enum):
    """Risk tolerance levels for different market conditions."""
    CONSERVATIVE = "conservative"  # High confidence, low risk
    MODERATE = "moderate"  # Balanced risk/reward
    AGGRESSIVE = "aggressive"  # Lower confidence, higher risk


# ============================================================================
# CONFIDENCE THRESHOLDS BY SIGNAL TYPE
# ============================================================================

# Conservative Profile (Recommended for Production Start)
CONSERVATIVE_THRESHOLDS: Dict[SignalType, Decimal] = {
    SignalType.INFLUENCER: Decimal("0.70"),  # Verified wallets = lower bar
    SignalType.CABAL: Decimal("0.85"),  # Pattern-based = higher bar
    SignalType.FRESH_WALLET: Decimal("0.90"),  # Riskiest = highest bar
    SignalType.PERPS: Decimal("0.80"),  # Derivatives = medium-high bar
    SignalType.HYBRID: Decimal("0.75"),  # Multi-signal = moderate bar
}

# Moderate Profile (After 1 Week of Successful Trading)
MODERATE_THRESHOLDS: Dict[SignalType, Decimal] = {
    SignalType.INFLUENCER: Decimal("0.65"),
    SignalType.CABAL: Decimal("0.80"),
    SignalType.FRESH_WALLET: Decimal("0.85"),
    SignalType.PERPS: Decimal("0.75"),
    SignalType.HYBRID: Decimal("0.70"),
}

# Aggressive Profile (Only for Bull Market + Proven Strategy)
AGGRESSIVE_THRESHOLDS: Dict[SignalType, Decimal] = {
    SignalType.INFLUENCER: Decimal("0.60"),
    SignalType.CABAL: Decimal("0.75"),
    SignalType.FRESH_WALLET: Decimal("0.80"),
    SignalType.PERPS: Decimal("0.70"),
    SignalType.HYBRID: Decimal("0.65"),
}


# ============================================================================
# ACTIVE CONFIGURATION
# ============================================================================

# Set the active risk profile (change this to switch profiles)
ACTIVE_PROFILE: RiskProfile = RiskProfile.CONSERVATIVE

# Get active thresholds based on profile
def get_active_thresholds() -> Dict[SignalType, Decimal]:
    """Returns the confidence thresholds for the currently active risk profile."""
    if ACTIVE_PROFILE == RiskProfile.CONSERVATIVE:
        return CONSERVATIVE_THRESHOLDS
    elif ACTIVE_PROFILE == RiskProfile.MODERATE:
        return MODERATE_THRESHOLDS
    elif ACTIVE_PROFILE == RiskProfile.AGGRESSIVE:
        return AGGRESSIVE_THRESHOLDS
    else:
        # Fallback to conservative
        return CONSERVATIVE_THRESHOLDS


def get_threshold(signal_type: SignalType) -> Decimal:
    """
    Get the minimum confidence threshold for a specific signal type.
    
    Args:
        signal_type: Type of signal being evaluated
        
    Returns:
        Minimum confidence threshold (0.0 - 1.0)
    """
    thresholds = get_active_thresholds()
    return thresholds.get(signal_type, Decimal("0.80"))  # Default fallback


def should_execute(signal_type: SignalType, confidence: Decimal) -> bool:
    """
    Determines if a signal meets the confidence threshold for execution.
    
    Args:
        signal_type: Type of signal
        confidence: Confidence score of the signal (0.0 - 1.0)
        
    Returns:
        True if signal should be executed, False otherwise
    """
    threshold = get_threshold(signal_type)
    return confidence >= threshold


# ============================================================================
# CATEGORY-BASED ADJUSTMENTS (Based on Influencer Categories)
# ============================================================================

# Adjust confidence thresholds based on wallet category
CATEGORY_MULTIPLIERS: Dict[str, Decimal] = {
    "memecoin": Decimal("1.0"),  # Standard threshold
    "defi": Decimal("0.95"),  # Slightly more lenient (DeFi is safer)
    "pumpfun": Decimal("1.05"),  # Stricter (pump.fun is risky)
    "perps": Decimal("1.02"),  # Slightly stricter (leverage)
    "nft": Decimal("0.98"),  # Slightly more lenient (rotation strategy)
    "hybrid": Decimal("1.0"),  # Standard
    "ecosystem": Decimal("0.90"),  # Most lenient (founders/OGs)
}


def get_adjusted_threshold(signal_type: SignalType, category: str = None) -> Decimal:
    """
    Get confidence threshold adjusted for wallet category.
    
    Args:
        signal_type: Type of signal
        category: Wallet category (memecoin, defi, etc.)
        
    Returns:
        Adjusted confidence threshold
    """
    base_threshold = get_threshold(signal_type)
    
    if category and category in CATEGORY_MULTIPLIERS:
        multiplier = CATEGORY_MULTIPLIERS[category]
        adjusted = base_threshold * multiplier
        # Clamp to valid range [0.5, 1.0]
        return max(Decimal("0.5"), min(Decimal("1.0"), adjusted))
    
    return base_threshold


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_profile_summary() -> str:
    """Returns a summary of the active confidence profile."""
    thresholds = get_active_thresholds()
    lines = [
        f"Active Risk Profile: {ACTIVE_PROFILE.value.upper()}",
        "─" * 50,
        "Signal Type          | Min Confidence",
        "─" * 50,
    ]
    
    for signal_type, threshold in thresholds.items():
        lines.append(f"{signal_type.value:20s} | {float(threshold):.2f}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Print configuration summary
    print(get_profile_summary())
    print("\n" + "="*50)
    print("Category Adjustments:")
    print("="*50)
    for category, multiplier in CATEGORY_MULTIPLIERS.items():
        print(f"{category:15s} | x{float(multiplier):.2f}")
