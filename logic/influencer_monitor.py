"""
Influencer Monitor - Logic for tracking high-signal wallet moves.
"""

import logging
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Set, Protocol
from datetime import datetime, timezone
import uuid

# We might want to move TradeSignal to a shared `models` package to avoid import loops
# For now, we'll define a local Signal structure or assume we pass dictionaries to Orchestrator

logger = logging.getLogger(__name__)

@dataclass
class InfluencerSignal:
    """Represents a trading signal derived from an influencer's action."""
    signal_id: str
    influencer_address: str
    token_mint: str
    action: str  # 'BUY', 'SELL'
    amount_in: Decimal
    amount_out: Decimal
    timestamp: datetime
    confidence: Decimal
    platform: str = "unknown"

class DatabaseClient(Protocol):
    """Protocol for DB access."""
    async def fetch(self, query: str, *args) -> list: ...
    async def execute(self, query: str, *args) -> None: ...

class InfluencerMonitor:
    """
    Monitors a whitelist of 'influencer' wallets for trading activity.
    
    Logic:
    1. Maintains a cache of known influencer addresses.
    2. Filters stream of transactions for these addresses.
    3. Decodes 'Buy' signals (Spending SOL/USDC -> Receiving Token).
    4. Emits high-confidence signals for the execution engine.
    """

    def __init__(self, db: DatabaseClient):
        self.db = db
        self.influencers: Set[str] = set()
        self.influencer_metadata: dict[str, dict] = {}
        self._last_refresh = datetime.min.replace(tzinfo=timezone.utc)

    async def refresh_whitelist(self):
        """Reloads the list of influencer wallets from the database."""
        query = """
            SELECT address, confidence, metadata 
            FROM tracked_wallets 
            WHERE category = 'influencer'
        """
        try:
            rows = await self.db.fetch(query)
            self.influencers = {row['address'] for row in rows}
            self.influencer_metadata = {
                row['address']: {
                    'confidence': row['confidence'],
                    'metadata': row['metadata']
                } 
                for row in rows
            }
            self._last_refresh = datetime.now(timezone.utc)
            print(f"DEBUG: Refreshed whitelist. Count: {len(self.influencers)}")
            print(f"DEBUG: Influencers: {list(self.influencers)[:3]}...")
            logger.info(f"Refreshed influencer whitelist: {len(self.influencers)} tracked.")
        except Exception as e:
            logger.error(f"Failed to refresh influencer whitelist: {e}")

    async def process_event(self, event_data: dict) -> Optional[InfluencerSignal]:
        """
        Analyzes a transaction event to see if it matches an influencer buy.
        
        Args:
            event_data: Dictionary containing transaction details 
                        (wallet_address, token_in, token_out, amount_in, etc.)
        """
        wallet = event_data.get('wallet_address')
        
        # 1. Quick Filter: Is this an influencer?
        if wallet not in self.influencers:
            return None

        # 2. Decode Action
        # specific logic depends on how 'event_data' is structured by Ingestion
        # Assuming event_data follows partial TransactionEvent structure
        
        token_in = event_data.get('token_in')   # What they sold (e.g. SOL)
        token_out = event_data.get('token_out') # What they bought
        
        if not token_in or not token_out:
            # print(f"DEBUG: Missing tokens in event: {wallet}") 
            return None

        # valid buy: Input is SOL/USDC, Output is something else
        is_buy = self._is_quote_token(token_in) and not self._is_quote_token(token_out)
        
        # print(f"DEBUG: Checking {wallet} | Buy? {is_buy} | In: {token_in} | Out: {token_out}")

        if is_buy:
            conf = self.influencer_metadata[wallet].get('confidence', Decimal("0.5"))
            
            signal = InfluencerSignal(
                signal_id=str(uuid.uuid4()),
                influencer_address=wallet,
                token_mint=token_out,
                action="BUY",
                amount_in=Decimal(str(event_data.get('amount_in', 0))),
                amount_out=Decimal(str(event_data.get('amount_out', 0))),
                timestamp=datetime.now(timezone.utc),
                confidence=conf,
                platform=event_data.get('program_id', 'unknown')
            )
            
            logger.info(f"🚨 INFLUENCER SIGNAL: {wallet[:8]} BOUGHT {token_out} (Conf: {conf})")
            return signal

        return None

    def _is_quote_token(self, mint: str) -> bool:
        """Returns true if mint is SOL or USDC/USDT."""
        quote_mints = {
            "So11111111111111111111111111111111111111112", # SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", # USDT
        }
        return mint in quote_mints
