"""Data models for the Fresh Wallet Matcher."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Optional
import json


@dataclass
class CEXWithdrawal:
    """Represents a withdrawal event from a centralized exchange."""
    
    tx_hash: str
    cex_source: str  # e.g., "Binance", "OKX", "Coinbase"
    amount: Decimal
    decimals: int
    timestamp: datetime
    target_address: Optional[str] = None  # Destination address if known
    
    def to_json(self) -> str:
        """Serialize to JSON for Redis storage."""
        return json.dumps({
            "tx_hash": self.tx_hash,
            "cex_source": self.cex_source,
            "amount": str(self.amount),
            "decimals": self.decimals,
            "timestamp": self.timestamp.isoformat(),
            "target_address": self.target_address,
        })
    
    @classmethod
    def from_json(cls, data: str) -> "CEXWithdrawal":
        """Deserialize from JSON."""
        parsed = json.loads(data)
        return cls(
            tx_hash=parsed["tx_hash"],
            cex_source=parsed["cex_source"],
            amount=Decimal(parsed["amount"]),
            decimals=parsed["decimals"],
            timestamp=datetime.fromisoformat(parsed["timestamp"]),
            target_address=parsed.get("target_address"),
        )


@dataclass
class FreshWallet:
    """Represents a newly-funded wallet detected on-chain."""
    
    address: str
    first_funded_tx: str
    first_funded_amount: Decimal
    first_funded_time: datetime
    tx_count: int = 0
    
    @property
    def is_truly_fresh(self) -> bool:
        """Returns True if this wallet has no prior transactions."""
        return self.tx_count == 0


@dataclass
class MatchResult:
    """Result of matching a CEX withdrawal to a fresh wallet."""
    
    withdrawal: CEXWithdrawal
    wallet: FreshWallet
    time_delta_ms: int
    amount_delta_pct: Decimal
    match_score: Decimal
    linked_parent_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def is_high_confidence(self) -> bool:
        """Returns True if match score exceeds 0.9."""
        return self.match_score >= Decimal("0.9")
    
    @property
    def is_exact_amount_match(self) -> bool:
        """Returns True if amount delta is within 0.1%."""
        return self.amount_delta_pct <= Decimal("0.001")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "cex_source": self.withdrawal.cex_source,
            "withdrawal_tx": self.withdrawal.tx_hash,
            "withdrawal_time": self.withdrawal.timestamp,
            "amount": self.withdrawal.amount,
            "decimals": self.withdrawal.decimals,
            "target_wallet": self.wallet.address,
            "target_tx_count": self.wallet.tx_count,
            "time_delta_ms": self.time_delta_ms,
            "match_score": self.match_score,
            "linked_parent": self.linked_parent_id,
        }
