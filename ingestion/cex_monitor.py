"""CEX Withdrawal Monitor - Detects transfers from known exchange hot wallets."""

import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Set

from .events import WithdrawalEvent
from .config import IngestionConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class CEXWithdrawalMonitor:
    """
    Monitors on-chain transfers from known CEX hot wallets.
    
    This class parses Solana transactions to detect withdrawals from
    centralized exchanges to user wallets. When a withdrawal to a
    fresh wallet (tx_count == 0) is detected, it triggers the Fresh
    Wallet Matcher for cabal detection.
    """
    
    def __init__(self, config: IngestionConfig = DEFAULT_CONFIG):
        """
        Initialize the CEX monitor.
        
        Args:
            config: Ingestion configuration with CEX wallet registry
        """
        self.config = config
        self.cex_wallets: Dict[str, str] = config.cex_hot_wallets.copy()
        self._processed_txs: Set[str] = set()
        self._max_cache_size = 10000
    
    def add_cex_wallet(self, address: str, exchange_name: str) -> None:
        """
        Add a CEX wallet to the monitoring set.
        
        Args:
            address: Solana wallet address
            exchange_name: Name of the exchange (e.g., "Binance")
        """
        self.cex_wallets[address] = exchange_name
        logger.info(f"Added CEX wallet: {address[:16]}... ({exchange_name})")
    
    def is_cex_wallet(self, address: str) -> bool:
        """Check if an address is a known CEX hot wallet."""
        return address in self.cex_wallets
    
    def get_exchange_name(self, address: str) -> Optional[str]:
        """Get the exchange name for a CEX wallet address."""
        return self.cex_wallets.get(address)
    
    def parse_transfer(
        self,
        tx_hash: str,
        slot: int,
        from_address: str,
        to_address: str,
        amount_lamports: int,
        recipient_tx_count: int = 0,
        timestamp: Optional[datetime] = None,
    ) -> Optional[WithdrawalEvent]:
        """
        Parse a transfer transaction and check if it's a CEX withdrawal.
        
        Args:
            tx_hash: Transaction signature
            slot: Slot number
            from_address: Sender address
            to_address: Recipient address
            amount_lamports: Amount in lamports (1 SOL = 1e9 lamports)
            recipient_tx_count: Number of prior transactions for recipient
            timestamp: Transaction timestamp (defaults to now)
            
        Returns:
            WithdrawalEvent if this is a CEX withdrawal, None otherwise
        """
        # Check if already processed
        if tx_hash in self._processed_txs:
            return None
        
        # Check if sender is a known CEX wallet
        if not self.is_cex_wallet(from_address):
            return None
        
        exchange_name = self.get_exchange_name(from_address)
        
        # Convert lamports to SOL
        amount_sol = Decimal(amount_lamports) / Decimal(10**9)
        
        # Create withdrawal event
        event = WithdrawalEvent(
            tx_hash=tx_hash,
            slot=slot,
            timestamp=timestamp or datetime.now(timezone.utc),
            cex_wallet=from_address,
            cex_name=exchange_name or "Unknown",
            recipient_wallet=to_address,
            amount=amount_sol,
            decimals=9,
            recipient_tx_count=recipient_tx_count,
        )
        
        # Cache processed tx
        self._processed_txs.add(tx_hash)
        if len(self._processed_txs) > self._max_cache_size:
            # Evict oldest entries (simple approach - in prod use LRU)
            to_remove = list(self._processed_txs)[:1000]
            for tx in to_remove:
                self._processed_txs.discard(tx)
        
        # Log detection
        log_level = logging.INFO if event.is_fresh_wallet_funding else logging.DEBUG
        logger.log(
            log_level,
            f"CEX withdrawal detected: {exchange_name} -> "
            f"{to_address[:16]}... ({amount_sol:.4f} SOL, "
            f"recipient_tx_count={recipient_tx_count})"
        )
        
        return event
    
    def parse_transaction_accounts(
        self,
        tx_hash: str,
        slot: int,
        pre_balances: list,
        post_balances: list,
        account_keys: list,
        timestamp: Optional[datetime] = None,
    ) -> list[WithdrawalEvent]:
        """
        Parse a transaction's balance changes to detect CEX withdrawals.
        
        This method analyzes the pre/post balance deltas to find transfers
        from CEX wallets. Useful for parsing raw transaction data from RPC.
        
        Args:
            tx_hash: Transaction signature
            slot: Slot number
            pre_balances: Account balances before transaction
            post_balances: Account balances after transaction
            account_keys: List of account public keys involved
            timestamp: Transaction timestamp
            
        Returns:
            List of WithdrawalEvent for any detected CEX withdrawals
        """
        events = []
        
        if len(pre_balances) != len(post_balances) != len(account_keys):
            logger.warning(f"Balance array length mismatch in {tx_hash}")
            return events
        
        # Find accounts with balance decreases (potential senders)
        for i, (pre, post, key) in enumerate(zip(pre_balances, post_balances, account_keys)):
            if pre > post and self.is_cex_wallet(key):
                # This CEX wallet sent funds
                sent_amount = pre - post
                
                # Find the recipient (account with matching increase)
                for j, (pre_r, post_r, key_r) in enumerate(zip(pre_balances, post_balances, account_keys)):
                    if i != j and post_r > pre_r:
                        received = post_r - pre_r
                        # Allow for gas difference
                        if abs(sent_amount - received) <= 10000:  # 0.00001 SOL tolerance
                            event = self.parse_transfer(
                                tx_hash=tx_hash,
                                slot=slot,
                                from_address=key,
                                to_address=key_r,
                                amount_lamports=received,
                                recipient_tx_count=0,  # Would need RPC call to determine
                                timestamp=timestamp,
                            )
                            if event:
                                events.append(event)
        
    async def process_high_speed_withdrawal(
        self,
        signature: str,
        sender: str,
        meta: object,
        account_keys: list[str]
    ) -> None:
        """
        Process a high-speed gRPC transaction update.
        
        Args:
            signature: Transaction signature
            sender: CEX hot wallet address (verified sender)
            meta: Transaction metadata containing balances
            account_keys: List of account public keys
        """
        # Extract balances from meta
        # Geyser protobuf definitions needed for exact field names, 
        # using standard convention here.
        try:
            pre_balances = meta.pre_token_balances  # Token balances
            post_balances = meta.post_token_balances
            
            # Note: For SOL transfers (which are usually what we care about for funding),
            # we need pre_balances/post_balances (SOL lamports) which are usually direct fields
            pre_sol = meta.pre_balances
            post_sol = meta.post_balances
            
            # Delegate to existing logic
            # We wrap in sync context since parse_transaction_accounts is sync
            # but this method is async for future expansion
            events = self.parse_transaction_accounts(
                tx_hash=signature,
                slot=0,  # Slot passed in meta if available, otherwise 0
                pre_balances=pre_sol,
                post_balances=post_sol,
                account_keys=account_keys,
            )
            
            # In a real system, we would trigger an async subscriber here
            # For now, we log the detection
            if events:
                logger.info(f"⚡ FAST-PATH: {len(events)} withdrawal(s) processed via Geyser")
                
        except Exception as e:
            logger.error(f"Failed to process high-speed withdrawal: {e}")
            
    def get_monitored_wallets(self) -> list[str]:
        """Get list of all monitored CEX wallet addresses."""
        return list(self.cex_wallets.keys())
