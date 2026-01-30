"""Data models for the Cabal Correlation Engine."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Set
import json


@dataclass
class CorrelationEvent:
    """
    Represents a contract interaction event that may indicate cabal activity.
    
    Multiple wallets interacting with the same contract within a short
    time window triggers correlation analysis.
    """
    
    contract_address: str
    slot: int
    timestamp: datetime
    wallet_address: str
    tx_hash: str
    action: str  # "swap", "mint", "stake", etc.
    token_address: Optional[str] = None
    amount: Optional[Decimal] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "contract_address": self.contract_address,
            "slot": self.slot,
            "timestamp": self.timestamp.isoformat(),
            "wallet_address": self.wallet_address,
            "tx_hash": self.tx_hash,
            "action": self.action,
            "token_address": self.token_address,
            "amount": str(self.amount) if self.amount else None,
        }


@dataclass
class WalletCluster:
    """
    Represents a cluster of wallets suspected to belong to the same entity.
    
    Clusters are formed when multiple wallets exhibit coordinated behavior
    such as interacting with the same contracts at similar times.
    """
    
    cluster_id: str
    wallets: Set[str] = field(default_factory=set)
    shared_contracts: Set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    avg_correlation_score: Decimal = Decimal("0")
    total_interactions: int = 0
    
    @property
    def size(self) -> int:
        """Number of wallets in the cluster."""
        return len(self.wallets)
    
    @property
    def is_active_cabal(self) -> bool:
        """
        Returns True if this cluster exhibits strong cabal characteristics.
        
        Criteria: 3+ wallets with 5+ shared contracts and correlation > 0.7
        """
        return (
            self.size >= 3 and 
            len(self.shared_contracts) >= 5 and
            self.avg_correlation_score >= Decimal("0.7")
        )
    
    def add_wallet(self, wallet_address: str) -> None:
        """Add a wallet to the cluster."""
        self.wallets.add(wallet_address)
        self.updated_at = datetime.utcnow()
    
    def add_shared_contract(self, contract_address: str) -> None:
        """Add a shared contract to the cluster."""
        self.shared_contracts.add(contract_address)
        self.updated_at = datetime.utcnow()
    
    def merge(self, other: "WalletCluster") -> None:
        """Merge another cluster into this one."""
        self.wallets.update(other.wallets)
        self.shared_contracts.update(other.shared_contracts)
        self.total_interactions += other.total_interactions
        self.updated_at = datetime.utcnow()
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "cluster_id": self.cluster_id,
            "wallets": list(self.wallets),
            "shared_contracts": list(self.shared_contracts),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "avg_correlation_score": str(self.avg_correlation_score),
            "total_interactions": self.total_interactions,
        }


@dataclass
class CorrelationResult:
    """
    Result of correlating wallets that interacted with the same contract.
    """
    
    wallet_a: str
    wallet_b: str
    correlation_score: Decimal
    shared_contracts: List[str]
    time_proximity_avg_ms: float
    co_occurrence_count: int
    contract_address: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def is_strong_correlation(self) -> bool:
        """Returns True if correlation is above 0.8."""
        return self.correlation_score >= Decimal("0.8")
    
    @property
    def is_weak_correlation(self) -> bool:
        """Returns True if correlation is between 0.5 and 0.7."""
        return Decimal("0.5") <= self.correlation_score < Decimal("0.7")
    
    def to_neo4j_params(self) -> dict:
        """Convert to parameters for Neo4j relationship creation."""
        return {
            "wallet_a": self.wallet_a,
            "wallet_b": self.wallet_b,
            "correlation_score": float(self.correlation_score),
            "shared_contracts": len(self.shared_contracts),
            "time_proximity_avg": self.time_proximity_avg_ms,
            "co_occurrence_count": self.co_occurrence_count,
            "detected_at": self.detected_at.isoformat(),
        }
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps({
            "wallet_a": self.wallet_a,
            "wallet_b": self.wallet_b,
            "correlation_score": str(self.correlation_score),
            "shared_contracts": self.shared_contracts,
            "time_proximity_avg_ms": self.time_proximity_avg_ms,
            "co_occurrence_count": self.co_occurrence_count,
            "contract_address": self.contract_address,
            "detected_at": self.detected_at.isoformat(),
        })
