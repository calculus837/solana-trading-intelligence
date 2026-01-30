"""Event types for the Ingestion Layer."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from enum import Enum
from typing import Optional
import json


class EventType(str, Enum):
    """Types of events emitted by the ingestion layer."""
    
    # Transaction events
    SWAP = "swap"
    TRANSFER = "transfer"
    MINT = "mint"
    BURN = "burn"
    
    # CEX events
    CEX_WITHDRAWAL = "cex_withdrawal"
    CEX_DEPOSIT = "cex_deposit"
    
    # Wallet events
    FRESH_WALLET_FUNDED = "fresh_wallet_funded"
    WALLET_FIRST_SWAP = "wallet_first_swap"
    
    # Program events
    PROGRAM_INTERACTION = "program_interaction"


@dataclass
class TransactionEvent:
    """Represents a parsed on-chain transaction event."""
    
    event_type: EventType
    tx_hash: str
    slot: int
    timestamp: datetime
    wallet_address: str
    program_id: Optional[str] = None
    token_in: Optional[str] = None
    token_out: Optional[str] = None
    amount_in: Optional[Decimal] = None
    amount_out: Optional[Decimal] = None
    fee: Optional[int] = None
    
    def to_json(self) -> str:
        """Serialize to JSON for Redis."""
        return json.dumps({
            "event_type": self.event_type.value,
            "tx_hash": self.tx_hash,
            "slot": self.slot,
            "timestamp": self.timestamp.isoformat(),
            "wallet_address": self.wallet_address,
            "program_id": self.program_id,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "amount_in": str(self.amount_in) if self.amount_in else None,
            "amount_out": str(self.amount_out) if self.amount_out else None,
            "fee": self.fee,
        })
    
    @classmethod
    def from_json(cls, data: str) -> "TransactionEvent":
        """Deserialize from JSON."""
        parsed = json.loads(data)
        return cls(
            event_type=EventType(parsed["event_type"]),
            tx_hash=parsed["tx_hash"],
            slot=parsed["slot"],
            timestamp=datetime.fromisoformat(parsed["timestamp"]),
            wallet_address=parsed["wallet_address"],
            program_id=parsed.get("program_id"),
            token_in=parsed.get("token_in"),
            token_out=parsed.get("token_out"),
            amount_in=Decimal(parsed["amount_in"]) if parsed.get("amount_in") else None,
            amount_out=Decimal(parsed["amount_out"]) if parsed.get("amount_out") else None,
            fee=parsed.get("fee"),
        )


@dataclass
class WithdrawalEvent:
    """Represents a CEX withdrawal event detected on-chain."""
    
    tx_hash: str
    slot: int
    timestamp: datetime
    cex_wallet: str
    cex_name: str
    recipient_wallet: str
    amount: Decimal
    decimals: int = 9  # SOL default
    recipient_tx_count: int = 0  # 0 indicates fresh wallet
    
    @property
    def is_fresh_wallet_funding(self) -> bool:
        """Returns True if this withdrawal funded a fresh wallet."""
        return self.recipient_tx_count == 0
    
    def to_json(self) -> str:
        """Serialize to JSON for Redis."""
        return json.dumps({
            "tx_hash": self.tx_hash,
            "slot": self.slot,
            "timestamp": self.timestamp.isoformat(),
            "cex_wallet": self.cex_wallet,
            "cex_name": self.cex_name,
            "recipient_wallet": self.recipient_wallet,
            "amount": str(self.amount),
            "decimals": self.decimals,
            "recipient_tx_count": self.recipient_tx_count,
        })
    
    @classmethod
    def from_json(cls, data: str) -> "WithdrawalEvent":
        """Deserialize from JSON."""
        parsed = json.loads(data)
        return cls(
            tx_hash=parsed["tx_hash"],
            slot=parsed["slot"],
            timestamp=datetime.fromisoformat(parsed["timestamp"]),
            cex_wallet=parsed["cex_wallet"],
            cex_name=parsed["cex_name"],
            recipient_wallet=parsed["recipient_wallet"],
            amount=Decimal(parsed["amount"]),
            decimals=parsed.get("decimals", 9),
            recipient_tx_count=parsed.get("recipient_tx_count", 0),
        )
