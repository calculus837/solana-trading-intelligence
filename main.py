#!/usr/bin/env python3
"""
Solana On-Chain Intelligence & Execution Engine

Main entry point that orchestrates all system components:
- Ingestion Layer: WebSocket streaming from Solana
- Fresh Wallet Matcher: CEX withdrawal correlation
- Cabal Correlation: Multi-wallet coordination detection
- Pre-flight Simulation: Honeypot detection
- Execution: Trade execution with MEV protection
- Analytics: PnL tracking and attribution

Usage:
    python main.py                  # Run full engine
    python main.py --mode ingest    # Run ingestion only
    python main.py --mode execute   # Run execution only
    python main.py --dry-run        # Paper trading mode
"""

import asyncio
import logging
import os
import signal
import sys
from decimal import Decimal
from typing import Optional
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("solana-intel")


class SolanaIntelEngine:
    """
    Main orchestrator for the Solana Intelligence Engine.
    
    Coordinates all subsystems:
    - Ingestion: Real-time blockchain data streaming
    - Intelligence: Pattern detection (Fresh Wallet, Cabal, Simulation)
    - Execution: Trade execution with risk management
    - Analytics: Performance tracking
    """
    
    def __init__(self, dry_run: bool = False):
        """
        Initialize the engine.
        
        Args:
            dry_run: If True, log trades but don't execute
        """
        self.dry_run = dry_run
        self._running = False
        self._tasks: list[asyncio.Task] = []
        
        # Components (initialized in setup)
        self.db_pool = None
        self.redis = None
        self.neo4j = None
        self.http_client = None
        
        # Subsystems
        self.ingestion_listener = None
        self.fresh_wallet_matcher = None
        self.cabal_engine = None
        self.simulator = None
        self.orchestrator = None
        self.circuit_breaker = None
        self.pnl_logger = None
        
        logger.info(
            f"🚀 Solana Intel Engine initializing... "
            f"{'[DRY RUN]' if dry_run else '[LIVE]'}"
        )
    
    async def setup(self) -> None:
        """Initialize all connections and subsystems."""
        logger.info("Setting up connections...")
        
        # PostgreSQL connection pool
        try:
            import asyncpg
            self.db_pool = await asyncpg.create_pool(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "solana_intel"),
                user=os.getenv("POSTGRES_USER", "admin"),
                password=os.getenv("POSTGRES_PASSWORD", "password"),
                min_size=2,
                max_size=10,
            )
            logger.info("✅ PostgreSQL connected")
        except Exception as e:
            logger.error(f"❌ PostgreSQL connection failed: {e}")
            raise
        
        # Redis connection
        try:
            import redis.asyncio as redis
            self.redis = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                decode_responses=True,
            )
            await self.redis.ping()
            logger.info("✅ Redis connected")
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed (optional): {e}")
            self.redis = None
        
        # Neo4j connection
        try:
            from neo4j import AsyncGraphDatabase
            self.neo4j = AsyncGraphDatabase.driver(
                os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                auth=(
                    os.getenv("NEO4J_USER", "neo4j"),
                    os.getenv("NEO4J_PASSWORD", "password"),
                ),
            )
            await self.neo4j.verify_connectivity()
            logger.info("✅ Neo4j connected")
        except Exception as e:
            logger.warning(f"⚠️ Neo4j connection failed (optional): {e}")
            self.neo4j = None
        
        # HTTP client for API calls
        try:
            import aiohttp
            self.http_session = aiohttp.ClientSession()
            logger.info("✅ HTTP client ready")
        except Exception as e:
            logger.error(f"❌ HTTP client failed: {e}")
            raise
        
        # Initialize subsystems
        await self._init_subsystems()
        
        logger.info("✅ All systems initialized")
    
    async def _init_subsystems(self) -> None:
        """Initialize intelligence and execution subsystems."""
        
        # Database wrapper for protocol compatibility
        db_client = DatabaseClientWrapper(self.db_pool)
        
        # Circuit Breaker (Risk Management)
        from logic.risk import CircuitBreaker, RiskLimits
        
        capital = float(os.getenv("TRADING_CAPITAL", "1000"))
        limits = RiskLimits(
            max_daily_drawdown_pct=Decimal(os.getenv("MAX_DAILY_DRAWDOWN_PCT", "0.10")),
            max_position_size_pct=Decimal(os.getenv("MAX_POSITION_SIZE_PCT", "0.05")),
        )
        
        self.circuit_breaker = CircuitBreaker(db_client, capital, limits)
        await self.circuit_breaker.load_state()
        logger.info(f"✅ Circuit Breaker ready (capital: {capital} SOL)")
        
        # Pre-flight Simulator
        from logic.simulation import TokenSimulator
        
        http_wrapper = HttpClientWrapper(self.http_session)
        rpc_wrapper = RpcClientWrapper(self.http_session)
        
        self.simulator = TokenSimulator(
            http_client=http_wrapper,
            rpc_client=rpc_wrapper,
            db_client=db_client,
        )
        logger.info("✅ Token Simulator ready")
        
        # PnL Logger
        from analytics import PnLLogger
        self.pnl_logger = PnLLogger(db_client)
        logger.info("✅ PnL Logger ready")
        
        # Cabal Correlation Engine (requires Neo4j)
        if self.neo4j:
            from logic.correlation import CabalCorrelationEngine
            graph_wrapper = GraphClientWrapper(self.neo4j)
            self.cabal_engine = CabalCorrelationEngine(db_client, graph_wrapper)
            logger.info("✅ Cabal Correlation Engine ready")
        
        # Fresh Wallet Matcher (requires Redis)
        if self.redis:
            from logic.matcher import CEXFreshWalletMatcher
            redis_wrapper = RedisClientWrapper(self.redis)
            if self.neo4j:
                graph_wrapper = GraphClientWrapper(self.neo4j)
                self.fresh_wallet_matcher = CEXFreshWalletMatcher(
                    redis_client=redis_wrapper,
                    db_client=db_client,
                    neo4j_client=graph_wrapper,
                )
                logger.info("✅ Fresh Wallet Matcher ready")
        
        # Execution Orchestrator (only if not dry run)
        if not self.dry_run:
            from execution import (
                ExecutionOrchestrator,
                SmartOrderRouter,
                SubWalletManager,
                JitoBundleSubmitter,
            )
            
            router = SmartOrderRouter(http_wrapper)
            jito = JitoBundleSubmitter(http_wrapper)
            subwallets = SubWalletManagerWrapper(db_client)
            
            self.orchestrator = ExecutionOrchestrator(
                simulator=self.simulator,
                circuit_breaker=self.circuit_breaker,
                router=router,
                subwallet_manager=subwallets,
                jito=jito,
                db_client=db_client,
                capital=capital,
            )
            logger.info("✅ Execution Orchestrator ready")
        else:
            logger.info("⏸️ Execution disabled (dry run)")
    
    async def run(self, mode: str = "full") -> None:
        """
        Run the engine.
        
        Args:
            mode: "full", "ingest", or "execute"
        """
        self._running = True
        
        try:
            if mode in ["full", "ingest"]:
                # Start ingestion listener
                await self._start_ingestion()
            
            if mode in ["full", "execute"]:
                # Start execution loop
                await self._start_execution_loop()
            
            # Keep running until stopped
            while self._running:
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logger.info("Shutdown requested...")
        finally:
            await self.shutdown()
    
    async def _start_ingestion(self) -> None:
        """Start the ingestion layer."""
        from ingestion import SolanaWebSocketListener, RedisEventPublisher, CEXWithdrawalMonitor
        
        if not self.redis:
            logger.warning("Redis not available, skipping ingestion")
            return
        
        publisher = RedisEventPublisher(self.redis)
        cex_monitor = CEXWithdrawalMonitor()
        
        # Check for Geyser config
        geyser_url = os.getenv("SOLANA_GEYSER_URL")
        geyser_token = os.getenv("SOLANA_GEYSER_TOKEN")
        
        if geyser_url and geyser_token and "api-key" not in geyser_token:
            # Initialize High-Performance Geyser Listener
            from ingestion.geyser import SolanaGeyserListener
            
            logger.info("⚡ Initializing Geyser gRPC Listener (High Performance Mode)")
            self.ingestion_listener = SolanaGeyserListener(
                endpoint=geyser_url,
                token=geyser_token,
                publisher=publisher,
                cex_monitor=cex_monitor,
            )
        else:
            # Fallback to Standard WebSocket
            logger.info("Standard WebSocket Listener initialized")
            self.ingestion_listener = SolanaWebSocketListener(
                publisher=publisher,
                cex_monitor=cex_monitor,
            )
        
        # Start listener as background task
        task = asyncio.create_task(
            self.ingestion_listener.start(),
            name="ingestion",
        )
        self._tasks.append(task)
        logger.info("🔄 Ingestion started")
    
    async def _start_execution_loop(self) -> None:
        """Start the execution monitoring loop."""
        
        async def execution_loop():
            """Main execution loop - check exits and process signals."""
            while self._running:
                try:
                    # Check if trading is allowed
                    if not await self.circuit_breaker.can_trade():
                        logger.warning("Trading halted by circuit breaker")
                        await asyncio.sleep(60)
                        continue
                    
                    # Check exit conditions for open positions
                    if self.orchestrator:
                        exits = await self.orchestrator.check_exits()
                        for exit_result in exits:
                            if exit_result.success:
                                logger.info(f"Exit executed: {exit_result.trade_id}")
                    
                    await asyncio.sleep(5)  # Check every 5 seconds
                    
                except Exception as e:
                    logger.error(f"Execution loop error: {e}")
                    await asyncio.sleep(10)
        
        task = asyncio.create_task(execution_loop(), name="execution")
        self._tasks.append(task)
        logger.info("🔄 Execution loop started")
    
    async def process_signal(self, signal: dict) -> None:
        """
        Process a trading signal from any source.
        
        Args:
            signal: Signal dict with token_mint, source, confidence
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would execute: {signal}")
            return
        
        if not self.orchestrator:
            logger.warning("Orchestrator not initialized")
            return
        
        from execution import TradeSignal, SignalSource
        
        trade_signal = TradeSignal(
            source=SignalSource(signal.get("source", "manual")),
            token_mint=signal["token_mint"],
            confidence=Decimal(str(signal.get("confidence", 0.5))),
        )
        
        result = await self.orchestrator.process_signal(trade_signal)
        
        if result.success:
            logger.info(f"✅ Trade executed: {result.trade_id}")
        else:
            logger.warning(f"❌ Trade failed: {result.error}")
    
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down...")
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Close connections
        if self.db_pool:
            await self.db_pool.close()
        if self.redis:
            await self.redis.close()
        if self.neo4j:
            await self.neo4j.close()
        if hasattr(self, 'http_session'):
            await self.http_session.close()
        
        logger.info("👋 Shutdown complete")


# ============================================================================
# Protocol Wrapper Classes
# ============================================================================

class DatabaseClientWrapper:
    """Wrapper to match DatabaseClient protocol."""
    
    def __init__(self, pool):
        self.pool = pool
    
    async def fetch(self, query: str, *args) -> list:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def execute(self, query: str, *args) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)


class HttpClientWrapper:
    """Wrapper for aiohttp to match HttpClient protocol."""
    
    def __init__(self, session):
        self.session = session
    
    async def get(self, url: str, params: dict = None) -> dict:
        async with self.session.get(url, params=params) as resp:
            return await resp.json()
    
    async def post(self, url: str, json: dict = None, headers: dict = None) -> dict:
        async with self.session.post(url, json=json, headers=headers) as resp:
            return await resp.json()


class RpcClientWrapper:
    """Wrapper for Solana RPC calls."""
    
    def __init__(self, session):
        self.session = session
        self.rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    
    async def simulate_transaction(self, tx_bytes: bytes) -> dict:
        import base64
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "simulateTransaction",
            "params": [base64.b64encode(tx_bytes).decode(), {"encoding": "base64"}],
        }
        async with self.session.post(self.rpc_url, json=payload) as resp:
            return await resp.json()
    
    async def get_recent_prioritization_fees(self, addresses: list = None) -> list:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getRecentPrioritizationFees",
            "params": [addresses] if addresses else [],
        }
        async with self.session.post(self.rpc_url, json=payload) as resp:
            result = await resp.json()
            return result.get("result", [])


class GraphClientWrapper:
    """Wrapper for Neo4j to match GraphClient protocol."""
    
    def __init__(self, driver):
        self.driver = driver
    
    async def run(self, query: str, **params) -> list:
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            return [dict(record) async for record in result]


class RedisClientWrapper:
    """Wrapper to match RedisClient protocol."""
    
    def __init__(self, redis):
        self.redis = redis
    
    async def setex(self, key: str, ttl: int, value: str) -> None:
        await self.redis.setex(key, ttl, value)
    
    async def get(self, key: str) -> Optional[str]:
        return await self.redis.get(key)
    
    async def lpush(self, key: str, *values) -> int:
        return await self.redis.lpush(key, *values)


class SubWalletManagerWrapper:
    """Minimal wrapper for SubWalletManager protocol."""
    
    def __init__(self, db_client):
        self.db = db_client
    
    async def get_available_wallet(self) -> dict:
        # Return a placeholder - full implementation in subwallets.py
        return {"address": "placeholder", "balance": 0}


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Solana On-Chain Intelligence & Execution Engine"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "ingest", "execute"],
        default="full",
        help="Run mode: full (all), ingest (data only), execute (trades only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Paper trading mode - log but don't execute trades",
    )
    
    args = parser.parse_args()
    
    # Create engine
    engine = SolanaIntelEngine(dry_run=args.dry_run)
    
    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info("Interrupt received, shutting down...")
        asyncio.get_event_loop().stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run
    async def run():
        await engine.setup()
        await engine.run(mode=args.mode)
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
