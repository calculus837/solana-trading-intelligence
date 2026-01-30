"""Tests for the Fresh Wallet Matcher module."""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta

from logic.matcher import (
    CEXWithdrawal,
    FreshWallet,
    MatchResult,
    CEXFreshWalletMatcher,
    MatcherConfig,
)


class TestModels:
    """Test data models."""
    
    def test_cex_withdrawal_json_roundtrip(self):
        """Test CEXWithdrawal serialization/deserialization."""
        withdrawal = CEXWithdrawal(
            tx_hash="abc123def456",
            cex_source="Binance",
            amount=Decimal("100.5"),
            decimals=9,
            timestamp=datetime(2026, 1, 1, 12, 0, 0),
        )
        
        json_str = withdrawal.to_json()
        restored = CEXWithdrawal.from_json(json_str)
        
        assert restored.tx_hash == withdrawal.tx_hash
        assert restored.cex_source == withdrawal.cex_source
        assert restored.amount == withdrawal.amount
        assert restored.decimals == withdrawal.decimals
    
    def test_fresh_wallet_is_truly_fresh(self):
        """Test freshness detection."""
        fresh = FreshWallet(
            address="wallet123",
            first_funded_tx="tx123",
            first_funded_amount=Decimal("100"),
            first_funded_time=datetime.utcnow(),
            tx_count=0,
        )
        assert fresh.is_truly_fresh is True
        
        not_fresh = FreshWallet(
            address="wallet456",
            first_funded_tx="tx456",
            first_funded_amount=Decimal("100"),
            first_funded_time=datetime.utcnow(),
            tx_count=5,
        )
        assert not_fresh.is_truly_fresh is False
    
    def test_match_result_high_confidence(self):
        """Test match result confidence detection."""
        withdrawal = CEXWithdrawal(
            tx_hash="tx1",
            cex_source="Binance",
            amount=Decimal("100"),
            decimals=9,
            timestamp=datetime.utcnow(),
        )
        wallet = FreshWallet(
            address="wallet1",
            first_funded_tx="tx2",
            first_funded_amount=Decimal("100"),
            first_funded_time=datetime.utcnow(),
            tx_count=0,
        )
        
        high = MatchResult(
            withdrawal=withdrawal,
            wallet=wallet,
            time_delta_ms=1000,
            amount_delta_pct=Decimal("0.001"),
            match_score=Decimal("0.95"),
        )
        assert high.is_high_confidence is True
        
        low = MatchResult(
            withdrawal=withdrawal,
            wallet=wallet,
            time_delta_ms=1000,
            amount_delta_pct=Decimal("0.001"),
            match_score=Decimal("0.8"),
        )
        assert low.is_high_confidence is False


class TestMatcherScoring:
    """Test the scoring algorithm."""
    
    def test_perfect_match_score(self):
        """Test scoring for an exact match."""
        config = MatcherConfig()
        
        # Create mock clients (not used in scoring)
        class MockRedis:
            async def setex(self, k, t, v): pass
            async def get(self, k): return None
        
        class MockDB:
            async def fetch(self, q, *a): return []
            async def execute(self, q, *a): pass
        
        class MockGraph:
            async def run(self, q, **p): pass
        
        matcher = CEXFreshWalletMatcher(MockRedis(), MockDB(), MockGraph(), config)
        
        now = datetime.utcnow()
        withdrawal = CEXWithdrawal(
            tx_hash="tx1",
            cex_source="Binance",
            amount=Decimal("100.000"),
            decimals=9,
            timestamp=now,
        )
        wallet = FreshWallet(
            address="wallet1",
            first_funded_tx="tx2",
            first_funded_amount=Decimal("100.000"),  # Exact match
            first_funded_time=now,  # Same time
            tx_count=0,  # Truly fresh
        )
        
        score = matcher._calculate_match_score(withdrawal, wallet)
        
        # Perfect time (1.0 * 0.4) + perfect amount (1.0 * 0.6) + freshness (0.1) = 1.1 -> capped at 1.0
        assert score == Decimal("1")
    
    def test_zero_score_for_late_match(self):
        """Test that matches outside time window get zero score."""
        config = MatcherConfig()
        
        class MockRedis:
            async def setex(self, k, t, v): pass
            async def get(self, k): return None
        
        class MockDB:
            async def fetch(self, q, *a): return []
            async def execute(self, q, *a): pass
        
        class MockGraph:
            async def run(self, q, **p): pass
        
        matcher = CEXFreshWalletMatcher(MockRedis(), MockDB(), MockGraph(), config)
        
        now = datetime.utcnow()
        withdrawal = CEXWithdrawal(
            tx_hash="tx1",
            cex_source="Binance",
            amount=Decimal("100"),
            decimals=9,
            timestamp=now,
        )
        wallet = FreshWallet(
            address="wallet1",
            first_funded_tx="tx2",
            first_funded_amount=Decimal("100"),
            first_funded_time=now + timedelta(minutes=10),  # 10 minutes later (> 5 min window)
            tx_count=0,
        )
        
        score = matcher._calculate_match_score(withdrawal, wallet)
        assert score == Decimal("0")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
