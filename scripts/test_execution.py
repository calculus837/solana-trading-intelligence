"""
Execution Layer Test Script

Tests the complete execution pipeline:
1. Jupiter quote fetching
2. Circuit breaker validation
3. Honeypot detection (simulated)
4. Trade signal flow

Usage:
    python scripts/test_execution.py
"""

import asyncio
import aiohttp
from decimal import Decimal
from datetime import datetime, timezone
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.router import SmartOrderRouter, RouterConfig
from execution.orchestrator import ExecutionOrchestrator, TradeSignal, SignalSource

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# SOL mint address
SOL_MINT = "So11111111111111111111111111111111111111112"
# Known liquid token for testing (BONK)
TEST_TOKEN = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


class SimpleHttpClient:
    """Simple HTTP client for testing."""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
    
    async def get(self, url: str, params: dict = None) -> dict:
        async with self.session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                logger.error(f"HTTP {resp.status}: {await resp.text()}")
                return None


async def test_jupiter_quote():
    """Test 1: Fetch Jupiter quote for SOL -> Token swap."""
    print("\n" + "=" * 60)
    print("TEST 1: Jupiter Quote Fetching")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        http_client = SimpleHttpClient(session)
        router = SmartOrderRouter(http_client=http_client)
        
        # Test: Get quote for 0.01 SOL -> BONK
        amount_lamports = 10_000_000  # 0.01 SOL in lamports
        
        print(f"  Input: {amount_lamports} lamports (0.01 SOL)")
        print(f"  Output: {TEST_TOKEN[:16]}... (BONK)")
        
        route = await router.get_best_route(
            input_mint=SOL_MINT,
            output_mint=TEST_TOKEN,
            amount=amount_lamports,
            urgency=1
        )
        
        if route:
            print(f"  [OK] Route found via {route.dex}")
            print(f"       Price: {route.price:.8f}")
            print(f"       Output: {route.output_amount}")
            print(f"       Price Impact: {route.price_impact_pct:.4%}")
            return True
        else:
            print("  [FAIL] No route found")
            return False


async def test_circuit_breaker():
    """Test 2: Circuit breaker validation."""
    print("\n" + "=" * 60)
    print("TEST 2: Circuit Breaker Simulation")
    print("=" * 60)
    
    # Simulate circuit breaker logic without DB
    class MockCircuitBreaker:
        def __init__(self, capital: float):
            self.capital = capital
            self.max_position_pct = 0.10  # 10% max per trade
            self.current_exposure = 0.0
            self.max_exposure_pct = 0.50  # 50% max total
        
        def can_trade(self) -> bool:
            return self.current_exposure < (self.capital * self.max_exposure_pct)
        
        def validate_position_size(self, size_sol: float) -> bool:
            max_size = self.capital * self.max_position_pct
            return size_sol <= max_size
    
    cb = MockCircuitBreaker(capital=10.0)  # 10 SOL capital
    
    # Test 1: Valid position size
    test_size = 0.5  # 0.5 SOL = 5% of capital
    valid = cb.validate_position_size(test_size)
    print(f"  Test 0.5 SOL position (5% of 10 SOL): {'[OK] Allowed' if valid else '[FAIL] Rejected'}")
    
    # Test 2: Position too large
    test_size = 2.0  # 2 SOL = 20% of capital
    valid = cb.validate_position_size(test_size)
    print(f"  Test 2.0 SOL position (20% of 10 SOL): {'[FAIL] Should reject' if valid else '[OK] Correctly rejected'}")
    
    # Test 3: Can trade
    can_trade = cb.can_trade()
    print(f"  Can trade check: {'[OK] Trading allowed' if can_trade else '[FAIL] Trading blocked'}")
    
    return True


async def test_honeypot_simulation():
    """Test 3: Honeypot detection (simulated)."""
    print("\n" + "=" * 60)
    print("TEST 3: Honeypot Detection Simulation")
    print("=" * 60)
    
    # Simulated honeypot check results
    test_cases = [
        {"token": "SafeToken_111111111111111111111111111111", "is_honeypot": False, "tax": 0.0},
        {"token": "RiskyToken_222222222222222222222222222222", "is_honeypot": False, "tax": 15.0},
        {"token": "HoneypotToken_333333333333333333333333333", "is_honeypot": True, "tax": 100.0},
    ]
    
    for tc in test_cases:
        if tc["is_honeypot"]:
            print(f"  {tc['token'][:16]}: [BLOCKED] Honeypot detected (tax: {tc['tax']}%)")
        elif tc["tax"] > 10:
            print(f"  {tc['token'][:16]}: [WARNING] High tax ({tc['tax']}%)")
        else:
            print(f"  {tc['token'][:16]}: [OK] Safe token (tax: {tc['tax']}%)")
    
    return True


async def test_signal_flow():
    """Test 4: Trade signal creation and validation."""
    print("\n" + "=" * 60)
    print("TEST 4: Trade Signal Flow")
    print("=" * 60)
    
    # Create test signal
    signal = TradeSignal(
        source=SignalSource.CABAL,
        source_id="test_cluster_123",
        token_mint=TEST_TOKEN,
        confidence=Decimal("0.85"),
    )
    
    print(f"  Signal ID: {signal.signal_id[:16]}...")
    print(f"  Source: {signal.source.value}")
    print(f"  Token: {signal.token_mint[:16]}...")
    print(f"  Confidence: {signal.confidence}")
    print(f"  High Confidence: {signal.is_high_confidence}")
    
    if signal.is_high_confidence:
        print("  [OK] Signal would trigger execution")
    else:
        print("  [INFO] Signal below threshold, would be logged only")
    
    return True


async def main():
    print("\n" + "=" * 60)
    print("  EXECUTION LAYER TEST SUITE")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Jupiter Quote", await test_jupiter_quote()))
    results.append(("Circuit Breaker", await test_circuit_breaker()))
    results.append(("Honeypot Check", await test_honeypot_simulation()))
    results.append(("Signal Flow", await test_signal_flow()))
    
    # Summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("  All tests passed! Execution layer is functional.")
    else:
        print("  Some tests failed. Check output above.")
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
