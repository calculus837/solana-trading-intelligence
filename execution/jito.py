"""Jito Bundle Submitter - MEV protection via Jito block engine."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Protocol, Tuple
from enum import Enum
import logging
import os
import random
import struct

logger = logging.getLogger(__name__)


# System Program ID for SOL transfers
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

# Transfer instruction discriminator (little-endian u32 = 2)
TRANSFER_INSTRUCTION_INDEX = 2


class BundleStatus(str, Enum):
    """Status of a Jito bundle."""
    PENDING = "pending"
    LANDED = "landed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class BundleResult:
    """Result of bundle submission."""
    
    bundle_id: str
    status: BundleStatus
    slot: Optional[int] = None
    error: Optional[str] = None
    tip_paid: int = 0
    tip_account: Optional[str] = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TipInstruction:
    """Represents a Jito tip instruction."""
    
    from_pubkey: str
    to_pubkey: str  # Jito tip account
    lamports: int
    
    def to_instruction_data(self) -> bytes:
        """
        Serialize the transfer instruction data.
        
        System Program Transfer layout:
        - u32 instruction index (2 for transfer)
        - u64 lamports amount
        """
        return struct.pack("<I", TRANSFER_INSTRUCTION_INDEX) + struct.pack("<Q", self.lamports)
    
    def to_dict(self) -> dict:
        """Convert to instruction dict for transaction building."""
        return {
            "program_id": SYSTEM_PROGRAM_ID,
            "accounts": [
                {"pubkey": self.from_pubkey, "is_signer": True, "is_writable": True},
                {"pubkey": self.to_pubkey, "is_signer": False, "is_writable": True},
            ],
            "data": self.to_instruction_data(),
        }


@dataclass
class JitoConfig:
    """Configuration for Jito bundle submission."""
    
    # Jito Block Engine URL (from environment)
    block_engine_url: str = field(
        default_factory=lambda: os.getenv(
            "JITO_BLOCK_ENGINE_URL",
            "https://mainnet.block-engine.jito.wtf"
        )
    )
    
    # Tip settings (in lamports)
    default_tip: int = 10_000  # 0.00001 SOL
    min_tip: int = 1_000
    max_tip: int = 1_000_000_000  # 1 SOL max
    
    # Official Jito tip accounts (2026)
    # Best practice: randomly select one per bundle for load distribution
    tip_accounts: List[str] = field(default_factory=lambda: [
        "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
        "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
        "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
        "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
        "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
        "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
        "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
        "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
    ])
    
    # Bundle settings
    max_transactions: int = 5
    bundle_timeout_seconds: float = 60.0
    
    # Whether to dynamically fetch tip accounts from Jito API
    dynamic_tip_accounts: bool = False


class HttpClient(Protocol):
    """Protocol for HTTP client."""
    async def post(self, url: str, json: dict = None, headers: dict = None) -> dict: ...
    async def get(self, url: str, params: dict = None) -> dict: ...


class JitoBundleSubmitter:
    """
    Submits transactions as Jito bundles for MEV protection.
    
    Jito bundles are sent directly to block producers (validators)
    via the Jito Block Engine, bypassing the public mempool.
    This prevents sandwich attacks and front-running.
    
    IMPORTANT: Every bundle MUST include a tip instruction as the LAST
    instruction in the final transaction. Without this tip, Jito validators
    have no incentive to prioritize your bundle.
    
    Usage:
        jito = JitoBundleSubmitter(http_client)
        
        # Create tip instruction
        tip_ix = jito.create_tip_instruction(
            payer="YourWalletPubkey...",
            tip_lamports=10000,
        )
        
        # Add tip to your final transaction (as last instruction)
        final_tx.add_instruction(tip_ix)
        
        # Submit bundle
        result = await jito.submit_bundle(
            transactions=[tx1_bytes, tx2_bytes, final_tx_bytes],
        )
    """
    
    def __init__(
        self,
        http_client: HttpClient,
        config: JitoConfig = None,
    ):
        """
        Initialize Jito bundle submitter.
        
        Args:
            http_client: HTTP client for API calls
            config: Jito configuration
        """
        self.http = http_client
        self.config = config or JitoConfig()
        self._cached_tip_accounts: Optional[List[str]] = None
    
    def get_random_tip_account(self) -> str:
        """
        Get a random tip account for load distribution.
        
        Best practice: Use random selection to distribute load
        across Jito infrastructure.
        
        Returns:
            Random Jito tip account address
        """
        accounts = self._cached_tip_accounts or self.config.tip_accounts
        return random.choice(accounts)
    
    async def fetch_tip_accounts(self) -> List[str]:
        """
        Dynamically fetch current tip accounts from Jito API.
        
        This ensures you always have the latest valid tip accounts.
        Falls back to hardcoded accounts if API fails.
        
        Returns:
            List of current Jito tip account addresses
        """
        if not self.config.dynamic_tip_accounts:
            return self.config.tip_accounts
        
        try:
            url = f"{self.config.block_engine_url}/api/v1/bundles"
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTipAccounts",
                "params": [],
            }
            
            response = await self.http.post(url, json=payload)
            
            if response and response.get("result"):
                accounts = response["result"]
                if accounts:
                    self._cached_tip_accounts = accounts
                    logger.info(f"Fetched {len(accounts)} tip accounts from Jito")
                    return accounts
        except Exception as e:
            logger.warning(f"Failed to fetch tip accounts, using defaults: {e}")
        
        return self.config.tip_accounts
    
    def create_tip_instruction(
        self,
        payer: str,
        tip_lamports: int = None,
    ) -> TipInstruction:
        """
        Create a tip instruction to include in your bundle.
        
        IMPORTANT: This instruction MUST be the LAST instruction in the
        FINAL transaction of your bundle.
        
        Args:
            payer: Payer's public key (base58 string)
            tip_lamports: Tip amount (defaults to config.default_tip)
            
        Returns:
            TipInstruction that can be added to a transaction
        
        Example:
            tip_ix = jito.create_tip_instruction(
                payer=wallet.pubkey,
                tip_lamports=10000,  # 0.00001 SOL
            )
            
            # Add to transaction
            transaction.add(tip_ix.to_dict())
        """
        tip_lamports = tip_lamports or self.config.default_tip
        tip_lamports = max(self.config.min_tip, min(tip_lamports, self.config.max_tip))
        
        tip_account = self.get_random_tip_account()
        
        logger.debug(f"Created tip instruction: {tip_lamports} lamports -> {tip_account[:16]}...")
        
        return TipInstruction(
            from_pubkey=payer,
            to_pubkey=tip_account,
            lamports=tip_lamports,
        )
    
    async def submit_bundle(
        self,
        transactions: List[bytes],
        tip: int = None,
    ) -> BundleResult:
        """
        Submit a bundle of transactions to Jito.
        
        IMPORTANT: Ensure the final transaction in your bundle includes
        a tip instruction as its last instruction. Use create_tip_instruction()
        to generate this.
        
        Args:
            transactions: List of serialized transactions (with tip in last tx)
            tip: Expected tip amount for logging (actual tip is in transaction)
            
        Returns:
            BundleResult with bundle ID and status
        """
        if len(transactions) > self.config.max_transactions:
            return BundleResult(
                bundle_id="",
                status=BundleStatus.FAILED,
                error=f"Too many transactions: {len(transactions)} > {self.config.max_transactions}",
            )
        
        if len(transactions) == 0:
            return BundleResult(
                bundle_id="",
                status=BundleStatus.FAILED,
                error="Bundle must contain at least one transaction",
            )
        
        tip = tip or self.config.default_tip
        
        try:
            import base64
            encoded_txs = [base64.b64encode(tx).decode() for tx in transactions]
            
            url = f"{self.config.block_engine_url}/api/v1/bundles"
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [encoded_txs],
            }
            
            headers = {
                "Content-Type": "application/json",
            }
            
            response = await self.http.post(url, json=payload, headers=headers)
            
            if response and response.get("result"):
                bundle_id = response["result"]
                logger.info(
                    f"✅ Bundle submitted: {bundle_id} | "
                    f"{len(transactions)} txs | tip ~{tip} lamports"
                )
                
                return BundleResult(
                    bundle_id=bundle_id,
                    status=BundleStatus.PENDING,
                    tip_paid=tip,
                )
            else:
                error = response.get("error", {}).get("message", "Unknown error")
                logger.error(f"Bundle rejected: {error}")
                return BundleResult(
                    bundle_id="",
                    status=BundleStatus.FAILED,
                    error=error,
                )
                
        except Exception as e:
            logger.error(f"Bundle submission failed: {e}")
            return BundleResult(
                bundle_id="",
                status=BundleStatus.FAILED,
                error=str(e),
            )
    
    async def submit_bundle_with_tip(
        self,
        transactions: List[bytes],
        payer: str,
        tip_lamports: int = None,
    ) -> Tuple[BundleResult, TipInstruction]:
        """
        Convenience method to submit a bundle and auto-generate tip instruction.
        
        NOTE: This returns the tip instruction for you to add to your final
        transaction BEFORE serializing. You must rebuild and re-serialize
        your final transaction with the tip instruction appended.
        
        Args:
            transactions: List of serialized transactions (WITHOUT tip)
            payer: Payer's public key for the tip
            tip_lamports: Tip amount in lamports
            
        Returns:
            Tuple of (BundleResult, TipInstruction to add to final tx)
        """
        tip_ix = self.create_tip_instruction(payer, tip_lamports)
        
        # Note: Caller must add tip_ix to their final transaction and re-serialize
        # This is a helper that generates the instruction
        
        logger.warning(
            "submit_bundle_with_tip requires you to add the returned "
            "TipInstruction to your final transaction before serializing!"
        )
        
        result = await self.submit_bundle(transactions, tip_lamports)
        result.tip_account = tip_ix.to_pubkey
        
        return result, tip_ix
    
    async def get_bundle_status(self, bundle_id: str) -> BundleResult:
        """
        Check the status of a submitted bundle.
        
        Args:
            bundle_id: Bundle ID from submit_bundle
            
        Returns:
            Updated BundleResult with current status
        """
        try:
            url = f"{self.config.block_engine_url}/api/v1/bundles"
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBundleStatuses",
                "params": [[bundle_id]],
            }
            
            response = await self.http.post(url, json=payload)
            
            if response and response.get("result"):
                statuses = response["result"].get("value", [])
                if statuses:
                    status_info = statuses[0]
                    
                    if status_info.get("confirmation_status") == "finalized":
                        logger.info(f"Bundle landed: {bundle_id} at slot {status_info.get('slot')}")
                        return BundleResult(
                            bundle_id=bundle_id,
                            status=BundleStatus.LANDED,
                            slot=status_info.get("slot"),
                        )
                    elif status_info.get("err"):
                        return BundleResult(
                            bundle_id=bundle_id,
                            status=BundleStatus.FAILED,
                            error=str(status_info.get("err")),
                        )
            
            return BundleResult(
                bundle_id=bundle_id,
                status=BundleStatus.PENDING,
            )
            
        except Exception as e:
            logger.error(f"Failed to get bundle status: {e}")
            return BundleResult(
                bundle_id=bundle_id,
                status=BundleStatus.PENDING,
                error=str(e),
            )
    
    def calculate_tip(
        self,
        urgency: int,
        bundle_size: int = 1,
        network_congestion: float = 1.0,
    ) -> int:
        """
        Calculate optimal tip based on urgency and conditions.
        
        Args:
            urgency: 1-5 urgency level (1=normal, 5=critical)
            bundle_size: Number of transactions in bundle
            network_congestion: Multiplier for network conditions (1.0=normal)
            
        Returns:
            Recommended tip amount in lamports
        """
        base_tip = self.config.default_tip
        
        # Exponential scaling by urgency
        urgency_multiplier = 2 ** (urgency - 1)
        
        # Linear scaling by bundle size
        size_multiplier = 1 + (bundle_size - 1) * 0.5
        
        # Network congestion factor
        congestion_multiplier = max(1.0, network_congestion)
        
        calculated = int(base_tip * urgency_multiplier * size_multiplier * congestion_multiplier)
        
        return max(self.config.min_tip, min(calculated, self.config.max_tip))


# Helper function for external use
def create_tip_transfer_data(lamports: int) -> bytes:
    """
    Create the data bytes for a System Program transfer instruction.
    
    This can be used with any Solana SDK to create the tip instruction.
    
    Args:
        lamports: Amount to transfer
        
    Returns:
        Serialized instruction data bytes
    """
    return struct.pack("<I", TRANSFER_INSTRUCTION_INDEX) + struct.pack("<Q", lamports)

