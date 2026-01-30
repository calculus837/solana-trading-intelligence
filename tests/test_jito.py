"""Tests for the Jito Bundle Submitter module."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import struct

from execution.jito import (
    JitoBundleSubmitter,
    JitoConfig,
    BundleResult,
    BundleStatus,
    TipInstruction,
    TRANSFER_INSTRUCTION_INDEX,
    create_tip_transfer_data,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_http():
    """Mock HTTP client."""
    http = AsyncMock()
    http.post = AsyncMock(return_value={
        "result": "bundle_id_123",
    })
    http.get = AsyncMock(return_value={})
    return http


@pytest.fixture
def default_config():
    """Default Jito configuration."""
    return JitoConfig()


@pytest.fixture
def jito_submitter(mock_http, default_config):
    """Create Jito submitter instance."""
    return JitoBundleSubmitter(mock_http, default_config)


# ============================================================================
# Unit Tests - JitoConfig
# ============================================================================

class TestJitoConfig:
    """Tests for JitoConfig data class."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = JitoConfig()
        
        assert config.default_tip == 10_000
        assert config.min_tip == 1_000
        assert config.max_tip == 1_000_000_000
        assert config.max_transactions == 5
        assert len(config.tip_accounts) == 8
    
    def test_tip_accounts_are_valid(self):
        """Test that tip accounts are valid base58 addresses."""
        config = JitoConfig()
        
        for account in config.tip_accounts:
            assert len(account) >= 32  # Base58 addresses are 32-44 chars
            assert len(account) <= 44


# ============================================================================
# Unit Tests - TipInstruction
# ============================================================================

class TestTipInstruction:
    """Tests for TipInstruction data class."""
    
    def test_creation(self):
        """Test tip instruction creation."""
        tip = TipInstruction(
            from_pubkey="FromAddress123",
            to_pubkey="ToAddress456",
            lamports=10000,
        )
        
        assert tip.from_pubkey == "FromAddress123"
        assert tip.to_pubkey == "ToAddress456"
        assert tip.lamports == 10000
    
    def test_to_instruction_data(self):
        """Test instruction data serialization."""
        tip = TipInstruction(
            from_pubkey="From",
            to_pubkey="To",
            lamports=50000,
        )
        
        data = tip.to_instruction_data()
        
        # Verify format: u32 (instruction index) + u64 (lamports)
        assert len(data) == 12  # 4 + 8 bytes
        
        # Parse back
        ix_index = struct.unpack("<I", data[:4])[0]
        lamports = struct.unpack("<Q", data[4:])[0]
        
        assert ix_index == TRANSFER_INSTRUCTION_INDEX
        assert lamports == 50000
    
    def test_to_dict(self):
        """Test conversion to instruction dict."""
        tip = TipInstruction(
            from_pubkey="FromPubkey",
            to_pubkey="ToPubkey",
            lamports=10000,
        )
        
        d = tip.to_dict()
        
        assert d["program_id"] == "11111111111111111111111111111111"
        assert len(d["accounts"]) == 2
        assert d["accounts"][0]["is_signer"] is True
        assert d["accounts"][1]["is_signer"] is False


class TestCreateTipTransferData:
    """Tests for create_tip_transfer_data helper function."""
    
    def test_creates_valid_data(self):
        """Test that function creates valid transfer data."""
        data = create_tip_transfer_data(100000)
        
        assert len(data) == 12
        
        ix_index = struct.unpack("<I", data[:4])[0]
        lamports = struct.unpack("<Q", data[4:])[0]
        
        assert ix_index == 2
        assert lamports == 100000


# ============================================================================
# Unit Tests - JitoBundleSubmitter
# ============================================================================

class TestJitoBundleSubmitter:
    """Tests for JitoBundleSubmitter class."""
    
    def test_get_random_tip_account(self, jito_submitter):
        """Test random tip account selection."""
        accounts = set()
        
        # Get 20 random accounts to ensure randomness
        for _ in range(20):
            account = jito_submitter.get_random_tip_account()
            accounts.add(account)
            assert account in jito_submitter.config.tip_accounts
        
        # Should have gotten more than one unique account
        assert len(accounts) > 1
    
    def test_create_tip_instruction(self, jito_submitter):
        """Test creating tip instruction."""
        tip = jito_submitter.create_tip_instruction(
            payer="MyWalletPubkey",
            tip_lamports=25000,
        )
        
        assert isinstance(tip, TipInstruction)
        assert tip.from_pubkey == "MyWalletPubkey"
        assert tip.lamports == 25000
        assert tip.to_pubkey in jito_submitter.config.tip_accounts
    
    def test_create_tip_instruction_default_amount(self, jito_submitter):
        """Test creating tip instruction with default amount."""
        tip = jito_submitter.create_tip_instruction(payer="Wallet")
        
        assert tip.lamports == jito_submitter.config.default_tip
    
    def test_create_tip_instruction_respects_min(self, jito_submitter):
        """Test that tip respects minimum."""
        tip = jito_submitter.create_tip_instruction(
            payer="Wallet",
            tip_lamports=100,  # Below minimum
        )
        
        assert tip.lamports == jito_submitter.config.min_tip
    
    def test_create_tip_instruction_respects_max(self, jito_submitter):
        """Test that tip respects maximum."""
        tip = jito_submitter.create_tip_instruction(
            payer="Wallet",
            tip_lamports=10_000_000_000,  # Above maximum
        )
        
        assert tip.lamports == jito_submitter.config.max_tip
    
    @pytest.mark.asyncio
    async def test_submit_bundle_success(self, jito_submitter, mock_http):
        """Test successful bundle submission."""
        transactions = [b"tx1", b"tx2"]
        
        result = await jito_submitter.submit_bundle(transactions)
        
        assert result.status == BundleStatus.PENDING
        assert result.bundle_id == "bundle_id_123"
        mock_http.post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_bundle_too_many_txs(self, jito_submitter):
        """Test bundle rejection for too many transactions."""
        transactions = [b"tx"] * 10  # Max is 5
        
        result = await jito_submitter.submit_bundle(transactions)
        
        assert result.status == BundleStatus.FAILED
        assert "Too many" in result.error
    
    @pytest.mark.asyncio
    async def test_submit_bundle_empty(self, jito_submitter):
        """Test bundle rejection for empty bundle."""
        result = await jito_submitter.submit_bundle([])
        
        assert result.status == BundleStatus.FAILED
        assert "at least one" in result.error
    
    @pytest.mark.asyncio
    async def test_submit_bundle_error_response(self, jito_submitter, mock_http):
        """Test handling of error response."""
        mock_http.post.return_value = {
            "error": {"message": "Invalid bundle"}
        }
        
        result = await jito_submitter.submit_bundle([b"tx1"])
        
        assert result.status == BundleStatus.FAILED
        assert "Invalid bundle" in result.error
    
    @pytest.mark.asyncio
    async def test_get_bundle_status_landed(self, jito_submitter, mock_http):
        """Test getting status of landed bundle."""
        mock_http.post.return_value = {
            "result": {
                "value": [{
                    "confirmation_status": "finalized",
                    "slot": 12345,
                }]
            }
        }
        
        result = await jito_submitter.get_bundle_status("bundle123")
        
        assert result.status == BundleStatus.LANDED
        assert result.slot == 12345
    
    @pytest.mark.asyncio
    async def test_get_bundle_status_failed(self, jito_submitter, mock_http):
        """Test getting status of failed bundle."""
        mock_http.post.return_value = {
            "result": {
                "value": [{
                    "err": "Transaction failed",
                }]
            }
        }
        
        result = await jito_submitter.get_bundle_status("bundle123")
        
        assert result.status == BundleStatus.FAILED
    
    @pytest.mark.asyncio
    async def test_get_bundle_status_pending(self, jito_submitter, mock_http):
        """Test getting status of pending bundle."""
        mock_http.post.return_value = {
            "result": {"value": []}  # Empty = still pending
        }
        
        result = await jito_submitter.get_bundle_status("bundle123")
        
        assert result.status == BundleStatus.PENDING
    
    def test_calculate_tip_normal_urgency(self, jito_submitter):
        """Test tip calculation for normal urgency."""
        tip = jito_submitter.calculate_tip(urgency=1)
        
        assert tip == jito_submitter.config.default_tip
    
    def test_calculate_tip_scales_with_urgency(self, jito_submitter):
        """Test tip scaling with urgency."""
        tip_1 = jito_submitter.calculate_tip(urgency=1)
        tip_3 = jito_submitter.calculate_tip(urgency=3)
        tip_5 = jito_submitter.calculate_tip(urgency=5)
        
        assert tip_1 < tip_3 < tip_5
    
    def test_calculate_tip_scales_with_bundle_size(self, jito_submitter):
        """Test tip scaling with bundle size."""
        tip_1tx = jito_submitter.calculate_tip(urgency=1, bundle_size=1)
        tip_5tx = jito_submitter.calculate_tip(urgency=1, bundle_size=5)
        
        assert tip_5tx > tip_1tx
    
    def test_calculate_tip_respects_max(self, jito_submitter):
        """Test tip calculation respects maximum."""
        tip = jito_submitter.calculate_tip(urgency=5, bundle_size=5)
        
        assert tip <= jito_submitter.config.max_tip


# ============================================================================
# Integration Tests
# ============================================================================

class TestJitoIntegration:
    """Integration tests for Jito workflow."""
    
    @pytest.mark.asyncio
    async def test_full_bundle_workflow(self, jito_submitter, mock_http):
        """Test complete bundle submission workflow."""
        # Create tip instruction
        tip = jito_submitter.create_tip_instruction(
            payer="UserWallet",
            tip_lamports=50000,
        )
        
        # Verify tip instruction
        assert tip.lamports == 50000
        
        # Submit bundle
        result = await jito_submitter.submit_bundle([b"tx_with_tip"])
        
        assert result.status == BundleStatus.PENDING
        assert result.bundle_id is not None
    
    @pytest.mark.asyncio
    async def test_fetch_tip_accounts_fallback(self, jito_submitter, mock_http):
        """Test tip account fetching with fallback."""
        # Disable dynamic fetching
        jito_submitter.config.dynamic_tip_accounts = False
        
        accounts = await jito_submitter.fetch_tip_accounts()
        
        assert accounts == jito_submitter.config.tip_accounts
    
    @pytest.mark.asyncio
    async def test_fetch_tip_accounts_dynamic(self, jito_submitter, mock_http):
        """Test dynamic tip account fetching."""
        jito_submitter.config.dynamic_tip_accounts = True
        mock_http.post.return_value = {
            "result": ["Account1", "Account2", "Account3"]
        }
        
        accounts = await jito_submitter.fetch_tip_accounts()
        
        assert accounts == ["Account1", "Account2", "Account3"]
        assert jito_submitter._cached_tip_accounts == accounts
