"""Priority Fee Manager - Dynamic Solana transaction priority fees."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Protocol
from enum import IntEnum
import logging

logger = logging.getLogger(__name__)


class Urgency(IntEnum):
    """Transaction urgency levels."""
    NORMAL = 1    # Standard fee, may take a few slots
    FAST = 2      # Higher fee for faster confirmation
    URGENT = 3    # High fee for next-block confirmation
    CRITICAL = 4  # Maximum fee for immediate confirmation


@dataclass
class FeeEstimate:
    """Priority fee estimate."""
    
    priority_fee: int  # microlamports per compute unit
    estimated_slots: int  # Expected slots until confirmation
    percentile: int  # Fee percentile (50, 75, 90, 99)
    total_fee_lamports: int  # Estimated total fee for a typical tx


@dataclass
class FeeConfig:
    """Configuration for priority fee calculation."""
    
    # Fee percentiles by urgency
    urgency_percentiles: dict = None
    
    # Compute unit limits
    default_compute_units: int = 200_000
    max_compute_units: int = 1_400_000
    
    # Fee caps (microlamports per CU)
    min_priority_fee: int = 1
    max_priority_fee: int = 10_000_000  # 10 SOL max per CU
    
    def __post_init__(self):
        if self.urgency_percentiles is None:
            self.urgency_percentiles = {
                Urgency.NORMAL: 50,
                Urgency.FAST: 75,
                Urgency.URGENT: 90,
                Urgency.CRITICAL: 99,
            }


class RpcClient(Protocol):
    """Protocol for Solana RPC client."""
    async def get_recent_prioritization_fees(self, addresses: list = None) -> list: ...


class PriorityFeeManager:
    """
    Dynamic priority fee calculator for Solana transactions.
    
    Uses recent prioritization fees from RPC to calculate
    optimal fees based on desired urgency level.
    
    Higher urgency = higher fee = faster confirmation
    """
    
    def __init__(
        self,
        rpc_client: RpcClient,
        config: FeeConfig = None,
    ):
        """
        Initialize priority fee manager.
        
        Args:
            rpc_client: Solana RPC client
            config: Fee configuration
        """
        self.rpc = rpc_client
        self.config = config or FeeConfig()
        self._fee_cache: Optional[list] = None
        self._cache_slot: int = 0
    
    async def get_recommended_fee(
        self,
        urgency: Urgency = Urgency.NORMAL,
        compute_units: int = None,
    ) -> FeeEstimate:
        """
        Get recommended priority fee for desired urgency.
        
        Args:
            urgency: Desired confirmation urgency
            compute_units: Expected compute units (default: 200k)
            
        Returns:
            FeeEstimate with recommended priority fee
        """
        compute_units = compute_units or self.config.default_compute_units
        
        # Get recent fees
        recent_fees = await self._get_recent_fees()
        
        if not recent_fees:
            # Fallback to minimum fee
            return FeeEstimate(
                priority_fee=self.config.min_priority_fee,
                estimated_slots=10,
                percentile=0,
                total_fee_lamports=compute_units * self.config.min_priority_fee // 1_000_000,
            )
        
        # Calculate percentile
        percentile = self.config.urgency_percentiles.get(urgency, 50)
        fee = self._calculate_percentile(recent_fees, percentile)
        
        # Clamp to limits
        fee = max(self.config.min_priority_fee, min(fee, self.config.max_priority_fee))
        
        # Estimate slots based on percentile
        estimated_slots = self._estimate_slots(percentile)
        
        # Calculate total fee
        total_fee = compute_units * fee // 1_000_000  # Convert microlamports to lamports
        
        return FeeEstimate(
            priority_fee=fee,
            estimated_slots=estimated_slots,
            percentile=percentile,
            total_fee_lamports=total_fee,
        )
    
    async def _get_recent_fees(self) -> list:
        """Get recent prioritization fees from RPC."""
        try:
            response = await self.rpc.get_recent_prioritization_fees()
            
            if response:
                # Extract fee values
                fees = [
                    entry.get("prioritizationFee", 0)
                    for entry in response
                    if entry.get("prioritizationFee", 0) > 0
                ]
                self._fee_cache = sorted(fees)
                return self._fee_cache
            
        except Exception as e:
            logger.error(f"Failed to get recent fees: {e}")
        
        return self._fee_cache or []
    
    def _calculate_percentile(self, fees: list, percentile: int) -> int:
        """Calculate percentile from fee list."""
        if not fees:
            return self.config.min_priority_fee
        
        index = int(len(fees) * percentile / 100)
        index = min(index, len(fees) - 1)
        return fees[index]
    
    def _estimate_slots(self, percentile: int) -> int:
        """Estimate slots until confirmation based on percentile."""
        if percentile >= 99:
            return 1
        elif percentile >= 90:
            return 2
        elif percentile >= 75:
            return 3
        elif percentile >= 50:
            return 5
        else:
            return 10
    
    def calculate_total_fee(
        self,
        priority_fee: int,
        compute_units: int,
        base_fee: int = 5000,  # Base fee in lamports
    ) -> int:
        """
        Calculate total transaction fee.
        
        Args:
            priority_fee: Priority fee in microlamports per CU
            compute_units: Compute units used
            base_fee: Base transaction fee in lamports
            
        Returns:
            Total fee in lamports
        """
        priority_cost = compute_units * priority_fee // 1_000_000
        return base_fee + priority_cost
