"""Tests for the Execution Orchestrator module."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

from execution.orchestrator import (
    ExecutionOrchestrator,
    TradeSignal,
    ExecutionResult,
    SignalSource,
    ExitTier,
    ExitStrategy,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_simulator():
    """Mock token simulator."""
    sim = AsyncMock()
    sim.check_honeypot = AsyncMock(return_value=False)
    return sim


@pytest.fixture
def mock_circuit_breaker():
    """Mock circuit breaker."""
    cb = AsyncMock()
    cb.can_trade = AsyncMock(return_value=True)
    cb.validate_position_size = AsyncMock(return_value=True)
    cb.record_position_opened = AsyncMock()
    return cb


@pytest.fixture
def mock_router():
    """Mock smart order router."""
    router = AsyncMock()
    router.get_best_route = AsyncMock(return_value={
        "price": 0.0001,
        "outAmount": 1000000,
        "fee": 1000,
    })
    return router


@pytest.fixture
def mock_subwallet():
    """Mock sub-wallet manager."""
    sw = AsyncMock()
    sw.get_available_wallet = AsyncMock(return_value={
        "address": "TestWallet123",
        "balance": 100,
    })
    return sw


@pytest.fixture
def mock_jito():
    """Mock Jito bundle submitter."""
    jito = AsyncMock()
    jito.submit_bundle = AsyncMock(return_value={"bundle_id": "test123"})
    return jito


@pytest.fixture
def mock_db():
    """Mock database client."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    return db


@pytest.fixture
def orchestrator(mock_simulator, mock_circuit_breaker, mock_router, 
                 mock_subwallet, mock_jito, mock_db):
    """Create orchestrator with all mocked dependencies."""
    return ExecutionOrchestrator(
        simulator=mock_simulator,
        circuit_breaker=mock_circuit_breaker,
        router=mock_router,
        subwallet_manager=mock_subwallet,
        jito=mock_jito,
        db_client=mock_db,
        capital=1000.0,
    )


# ============================================================================
# Unit Tests - TradeSignal
# ============================================================================

class TestTradeSignal:
    """Tests for TradeSignal data class."""
    
    def test_default_signal(self):
        """Test default signal creation."""
        signal = TradeSignal(
            token_mint="TestToken123",
            confidence=Decimal("0.85"),
        )
        
        assert signal.token_mint == "TestToken123"
        assert signal.confidence == Decimal("0.85")
        assert signal.source == SignalSource.CABAL
        assert signal.signal_id is not None
    
    def test_high_confidence_property(self):
        """Test is_high_confidence property."""
        high_conf = TradeSignal(token_mint="X", confidence=Decimal("0.9"))
        low_conf = TradeSignal(token_mint="X", confidence=Decimal("0.5"))
        
        assert high_conf.is_high_confidence is True
        assert low_conf.is_high_confidence is False


class TestExecutionResult:
    """Tests for ExecutionResult data class."""
    
    def test_success_result(self):
        """Test successful execution result."""
        result = ExecutionResult(
            success=True,
            trade_id="abc123",
            entry_price=Decimal("0.0001"),
        )
        
        assert result.success is True
        assert "SUCCESS" in str(result)
    
    def test_failed_result(self):
        """Test failed execution result."""
        result = ExecutionResult(
            success=False,
            error="Honeypot detected",
        )
        
        assert result.success is False
        assert "FAILED" in str(result)
        assert "Honeypot" in str(result)


class TestExitStrategy:
    """Tests for ExitStrategy configuration."""
    
    def test_default_tiers(self):
        """Test default exit tier configuration."""
        strategy = ExitStrategy()
        
        assert strategy.t1_multiplier == Decimal("2.0")
        assert strategy.t1_sell_pct == Decimal("0.50")
        assert strategy.t2_multiplier == Decimal("5.0")
        assert strategy.t3_multiplier == Decimal("10.0")
        assert strategy.stop_loss_pct == Decimal("-0.30")


# ============================================================================
# Unit Tests - ExecutionOrchestrator
# ============================================================================

class TestExecutionOrchestrator:
    """Tests for ExecutionOrchestrator class."""
    
    @pytest.mark.asyncio
    async def test_process_signal_success(self, orchestrator):
        """Test successful signal processing."""
        signal = TradeSignal(
            token_mint="Token123",
            confidence=Decimal("0.85"),
            source=SignalSource.CABAL,
        )
        
        result = await orchestrator.process_signal(signal)
        
        assert result.success is True
        assert result.trade_id is not None
    
    @pytest.mark.asyncio
    async def test_process_signal_blocked_by_circuit_breaker(
        self, orchestrator, mock_circuit_breaker
    ):
        """Test signal blocked by circuit breaker."""
        mock_circuit_breaker.can_trade.return_value = False
        
        signal = TradeSignal(token_mint="Token123", confidence=Decimal("0.8"))
        result = await orchestrator.process_signal(signal)
        
        assert result.success is False
        assert "Circuit breaker" in result.error
    
    @pytest.mark.asyncio
    async def test_process_signal_blocked_by_honeypot(
        self, orchestrator, mock_simulator
    ):
        """Test signal blocked by honeypot detection."""
        mock_simulator.check_honeypot.return_value = True
        
        signal = TradeSignal(token_mint="Token123", confidence=Decimal("0.8"))
        result = await orchestrator.process_signal(signal)
        
        assert result.success is False
        assert "honeypot" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_process_signal_blocked_by_position_size(
        self, orchestrator, mock_circuit_breaker
    ):
        """Test signal blocked by position size limits."""
        mock_circuit_breaker.validate_position_size.return_value = False
        
        signal = TradeSignal(token_mint="Token123", confidence=Decimal("0.8"))
        result = await orchestrator.process_signal(signal)
        
        assert result.success is False
        assert "size" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_process_signal_no_route(self, orchestrator, mock_router):
        """Test signal fails when no route available."""
        mock_router.get_best_route.return_value = None
        
        signal = TradeSignal(token_mint="Token123", confidence=Decimal("0.8"))
        result = await orchestrator.process_signal(signal)
        
        assert result.success is False
        assert "route" in result.error.lower()
    
    def test_calculate_position_size(self, orchestrator):
        """Test position size calculation based on confidence."""
        # Low confidence = smaller position
        low_size = orchestrator._calculate_position_size(Decimal("0.5"))
        # High confidence = larger position
        high_size = orchestrator._calculate_position_size(Decimal("1.0"))
        
        assert high_size > low_size
        # Max is 5% of capital = 50 SOL
        assert high_size <= Decimal("50")
    
    def test_position_size_scales_with_confidence(self, orchestrator):
        """Test that position size properly scales."""
        size_50 = orchestrator._calculate_position_size(Decimal("0.5"))
        size_75 = orchestrator._calculate_position_size(Decimal("0.75"))
        size_100 = orchestrator._calculate_position_size(Decimal("1.0"))
        
        assert size_50 < size_75 < size_100


# ============================================================================
# Exit Strategy Tests
# ============================================================================

class TestExitLogic:
    """Tests for exit strategy logic."""
    
    @pytest.mark.asyncio
    async def test_check_exits_no_positions(self, orchestrator):
        """Test check_exits with no open positions."""
        results = await orchestrator.check_exits()
        assert results == []
    
    @pytest.mark.asyncio
    async def test_track_active_position(self, orchestrator, mock_db):
        """Test that positions are tracked after execution."""
        signal = TradeSignal(token_mint="Token123", confidence=Decimal("0.8"))
        
        result = await orchestrator.process_signal(signal)
        
        assert result.success is True
        assert len(orchestrator._active_positions) == 1
        
        trade_id = result.trade_id
        assert trade_id in orchestrator._active_positions
        assert orchestrator._active_positions[trade_id]["token_mint"] == "Token123"


# ============================================================================
# Integration Tests
# ============================================================================

class TestOrchestratorIntegration:
    """Integration tests for orchestrator workflow."""
    
    @pytest.mark.asyncio
    async def test_full_trade_workflow(self, orchestrator, mock_db):
        """Test complete trade workflow from signal to execution."""
        # Create high-confidence signal
        signal = TradeSignal(
            source=SignalSource.CABAL,
            token_mint="HighConfToken",
            confidence=Decimal("0.95"),
        )
        
        # Process signal
        result = await orchestrator.process_signal(signal)
        
        # Verify success
        assert result.success is True
        
        # Verify DB was called for trade log
        mock_db.execute.assert_called()
        
        # Verify position is tracked
        assert len(orchestrator._active_positions) == 1
    
    @pytest.mark.asyncio
    async def test_signal_source_types(self, orchestrator):
        """Test different signal sources."""
        sources = [
            SignalSource.CABAL,
            SignalSource.INFLUENCER,
            SignalSource.FRESH_WALLET,
            SignalSource.MANUAL,
        ]
        
        for source in sources:
            signal = TradeSignal(
                source=source,
                token_mint=f"Token_{source.value}",
                confidence=Decimal("0.8"),
            )
            
            result = await orchestrator.process_signal(signal)
            assert result.success is True
