"""Tests for the Circuit Breaker risk management module."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from logic.risk.circuit_breaker import (
    CircuitBreaker,
    RiskLimits,
    LockdownState,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db():
    """Create a mock database client."""
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    db.execute = AsyncMock()
    return db


@pytest.fixture
def default_limits():
    """Default risk limits for testing."""
    return RiskLimits(
        max_daily_drawdown_pct=Decimal("0.10"),
        max_single_trade_pct=Decimal("0.02"),
        max_position_size_pct=Decimal("0.05"),
        max_open_positions=10,
        max_consecutive_losses=3,
        lockdown_hours=24,
    )


@pytest.fixture
def circuit_breaker(mock_db, default_limits):
    """Create a circuit breaker instance."""
    return CircuitBreaker(
        db_client=mock_db,
        capital=1000.0,
        limits=default_limits,
    )


# ============================================================================
# Unit Tests - RiskLimits
# ============================================================================

class TestRiskLimits:
    """Tests for RiskLimits configuration."""
    
    def test_default_values(self):
        """Test default risk limit values."""
        limits = RiskLimits()
        
        assert limits.max_daily_drawdown_pct == Decimal("0.10")
        assert limits.max_single_trade_pct == Decimal("0.02")
        assert limits.max_position_size_pct == Decimal("0.05")
        assert limits.max_open_positions == 10
        assert limits.max_consecutive_losses == 3
        assert limits.lockdown_hours == 24
    
    def test_custom_values(self):
        """Test custom risk limit values."""
        limits = RiskLimits(
            max_daily_drawdown_pct=Decimal("0.15"),
            max_open_positions=5,
        )
        
        assert limits.max_daily_drawdown_pct == Decimal("0.15")
        assert limits.max_open_positions == 5


# ============================================================================
# Unit Tests - LockdownState
# ============================================================================

class TestLockdownState:
    """Tests for LockdownState data class."""
    
    def test_default_state(self):
        """Test default lockdown state."""
        state = LockdownState()
        
        assert state.is_locked is False
        assert state.locked_at is None
        assert state.daily_pnl == Decimal("0")
        assert state.consecutive_losses == 0
    
    def test_locked_state(self):
        """Test locked state."""
        now = datetime.now(timezone.utc)
        state = LockdownState(
            is_locked=True,
            locked_at=now,
            lock_reason="Test lockdown",
        )
        
        assert state.is_locked is True
        assert state.lock_reason == "Test lockdown"


# ============================================================================
# Unit Tests - CircuitBreaker
# ============================================================================

class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""
    
    @pytest.mark.asyncio
    async def test_can_trade_when_unlocked(self, circuit_breaker):
        """Test that trading is allowed when not locked."""
        # Initialize state
        circuit_breaker._state = LockdownState()
        
        result = await circuit_breaker.can_trade()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cannot_trade_when_locked(self, circuit_breaker):
        """Test that trading is blocked when locked."""
        circuit_breaker._state = LockdownState(
            is_locked=True,
            unlock_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        
        result = await circuit_breaker.can_trade()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_auto_unlock_when_expired(self, circuit_breaker, mock_db):
        """Test automatic unlock when lockdown expires."""
        circuit_breaker._state = LockdownState(
            is_locked=True,
            unlock_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Expired
        )
        
        result = await circuit_breaker.can_trade()
        assert result is True
        assert circuit_breaker._state.is_locked is False
    
    @pytest.mark.asyncio
    async def test_validate_position_size_within_limits(self, circuit_breaker):
        """Test position size validation within limits."""
        # 5% of 1000 = 50 SOL max
        result = await circuit_breaker.validate_position_size(40.0)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_validate_position_size_exceeds_limits(self, circuit_breaker):
        """Test position size validation exceeding limits."""
        # 5% of 1000 = 50 SOL max, 60 exceeds
        result = await circuit_breaker.validate_position_size(60.0)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_record_winning_trade(self, circuit_breaker, mock_db):
        """Test recording a winning trade."""
        circuit_breaker._state = LockdownState()
        
        result = await circuit_breaker.record_trade_result(
            pnl=100.0,
            is_win=True,
            position_size=50.0,
        )
        
        assert result is True
        assert circuit_breaker._state.daily_pnl == Decimal("100")
        assert circuit_breaker._state.consecutive_losses == 0
    
    @pytest.mark.asyncio
    async def test_record_losing_trade(self, circuit_breaker, mock_db):
        """Test recording a losing trade increments consecutive losses."""
        circuit_breaker._state = LockdownState()
        
        result = await circuit_breaker.record_trade_result(
            pnl=-20.0,
            is_win=False,
            position_size=50.0,
        )
        
        assert result is True
        assert circuit_breaker._state.daily_pnl == Decimal("-20")
        assert circuit_breaker._state.consecutive_losses == 1
    
    @pytest.mark.asyncio
    async def test_lockdown_on_consecutive_losses(self, circuit_breaker, mock_db):
        """Test lockdown triggers on consecutive losses."""
        circuit_breaker._state = LockdownState(consecutive_losses=2)
        
        # Third consecutive loss should trigger lockdown
        result = await circuit_breaker.record_trade_result(
            pnl=-20.0,
            is_win=False,
        )
        
        assert result is False
        assert circuit_breaker._state.is_locked is True
        assert "Consecutive losses" in circuit_breaker._state.lock_reason
    
    @pytest.mark.asyncio
    async def test_lockdown_on_daily_drawdown(self, circuit_breaker, mock_db):
        """Test lockdown triggers on daily drawdown limit."""
        # Start with some existing loss
        circuit_breaker._state = LockdownState(
            daily_pnl=Decimal("-80"),  # Already down 8%
        )
        
        # Another loss pushes over 10% drawdown
        result = await circuit_breaker.record_trade_result(
            pnl=-50.0,  # Total now -130, which is > 10% of 1000
            is_win=False,
        )
        
        assert result is False
        assert circuit_breaker._state.is_locked is True
        assert "drawdown" in circuit_breaker._state.lock_reason.lower()
    
    @pytest.mark.asyncio
    async def test_max_positions_blocks_trading(self, circuit_breaker):
        """Test that max open positions blocks new trades."""
        circuit_breaker._state = LockdownState(open_position_count=10)
        
        result = await circuit_breaker.can_trade()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_record_position_opened(self, circuit_breaker, mock_db):
        """Test recording a new position."""
        circuit_breaker._state = LockdownState()
        
        await circuit_breaker.record_position_opened(50.0)
        
        assert circuit_breaker._state.open_position_count == 1
        assert circuit_breaker._state.total_exposure == Decimal("50")
    
    @pytest.mark.asyncio
    async def test_force_unlock(self, circuit_breaker, mock_db):
        """Test force unlock."""
        circuit_breaker._state = LockdownState(
            is_locked=True,
            lock_reason="Test",
        )
        
        await circuit_breaker.force_unlock()
        
        assert circuit_breaker._state.is_locked is False
        assert circuit_breaker._state.daily_pnl == Decimal("0")


# ============================================================================
# Integration Tests
# ============================================================================

class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with database."""
    
    @pytest.mark.asyncio
    async def test_load_state_from_db(self, mock_db, default_limits):
        """Test loading state from database."""
        mock_db.fetch.return_value = [{
            "is_locked": True,
            "locked_at": datetime.now(timezone.utc),
            "lock_reason": "Test reason",
            "unlock_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "daily_pnl": Decimal("-50"),
            "daily_pnl_pct": Decimal("-0.05"),
            "consecutive_losses": 2,
            "open_position_count": 3,
            "total_exposure": Decimal("150"),
            "last_trade_time": datetime.now(timezone.utc),
        }]
        
        breaker = CircuitBreaker(mock_db, 1000.0, default_limits)
        state = await breaker.load_state()
        
        assert state.is_locked is True
        assert state.lock_reason == "Test reason"
        assert state.consecutive_losses == 2
    
    @pytest.mark.asyncio
    async def test_save_state_to_db(self, circuit_breaker, mock_db):
        """Test saving state to database."""
        circuit_breaker._state = LockdownState(
            is_locked=True,
            daily_pnl=Decimal("-100"),
        )
        
        await circuit_breaker.save_state()
        
        mock_db.execute.assert_called_once()
