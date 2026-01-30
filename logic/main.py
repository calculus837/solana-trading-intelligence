"""
Logic Engine - Main entry point for correlation and cabal detection.

This module:
1. Subscribes to Redis streams for raw events
2. Runs the CabalCorrelationEngine to detect coordinated wallets
3. Runs the FreshClusterMatcher for CEX forensics
4. Publishes detected cabals/signals to solana:alerts
5. Triggers ExecutionOrchestrator for automated trading
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from dotenv import load_dotenv
import asyncpg
import redis.asyncio as redis
from neo4j import AsyncGraphDatabase

from .correlation.engine import CabalCorrelationEngine
from .correlation.models import CorrelationEvent
from .matcher.matcher import CEXFreshWalletMatcher
from .matcher.models import CEXWithdrawal, FreshWallet, MatchResult
from .influencer_monitor import InfluencerMonitor
from .notifications.telegram import TelegramNotifier
from .config import SignalType, should_execute, get_adjusted_threshold

import aiohttp
import base64

# Execution imports
from execution.orchestrator import ExecutionOrchestrator, TradeSignal, SignalSource
from execution.jupiter_client import JupiterClient
from execution.subwallets import SubWalletManager
from execution.jito import JitoBundleSubmitter
from execution.key_manager import AESKeyManager
from logic.risk.circuit_breaker import CircuitBreaker
from logic.simulation.simulator import TokenSimulator

load_dotenv()

# Configuration
REDIS_URL = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}"
POSTGRES_DSN = f"postgresql://{os.getenv('POSTGRES_USER', 'admin')}:{os.getenv('POSTGRES_PASSWORD', 'password')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'solana_intel')}"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))

# Auto-execution configuration
AUTO_EXECUTE = os.getenv("AUTO_EXECUTE", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
# MIN_CONFIDENCE now managed by logic/config/confidence.py per-strategy thresholds
MAX_POSITION_SOL = Decimal(os.getenv("MAX_POSITION_SOL", "10.0"))
TRADING_CAPITAL = Decimal(os.getenv("TRADING_CAPITAL", "100.0"))
KEY_ENCRYPTION_SECRET = os.getenv("KEY_ENCRYPTION_SECRET", "default-secret-change-me-in-prod-12345")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

# Configure logging
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# Add file handler for background diagnostics
file_handler = logging.FileHandler("logic_engine.log")
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(file_handler)

class LogicEngine:
    """Main logic engine that orchestrates all detection modules."""
    
    def __init__(self, dry_run: bool = None):
        self.db_pool: Optional[asyncpg.Pool] = None
        self.neo4j_driver = None
        self.redis_client = None
        
        self.cabal_engine: Optional[CabalCorrelationEngine] = None
        self.fresh_matcher: Optional[CEXFreshWalletMatcher] = None
        self.influencer_monitor: Optional[InfluencerMonitor] = None
        
        # Execution layer
        self.orchestrator: Optional[ExecutionOrchestrator] = None
        self.circuit_breaker: Optional[CircuitBreaker] = None
        self.jupiter_client: Optional[JupiterClient] = None
        
        self.telegram: Optional[TelegramNotifier] = None
        
        # Use argument or fall back to env var
        self.dry_run = dry_run if dry_run is not None else DRY_RUN
        self.auto_execute = AUTO_EXECUTE
        
        self._running = False
    
    async def start(self):
        """Initialize connections and start processing."""
        logger.info("Starting Logic Engine...")
        logger.info(f"   AUTO_EXECUTE: {self.auto_execute} | DRY_RUN: {self.dry_run}")
        
        # Connect to PostgreSQL
        try:
            logger.info(f"Connecting to PostgreSQL at {POSTGRES_DSN.split('@')[-1]}...")
            self.db_pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=2, max_size=10)
            logger.info("PostgreSQL connected")
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            raise
        
        # Connect to Neo4j
        try:
            logger.info(f"Connecting to Neo4j at {NEO4J_URI}...")
            self.neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
            # Use try/except with timeout for connectivity check
            await asyncio.wait_for(self.neo4j_driver.verify_connectivity(), timeout=5.0)
            logger.info("Neo4j connected")
        except asyncio.TimeoutError:
            logger.warning("Neo4j connection timed out - continuing without graph updates")
            self.neo4j_driver = None
        except Exception as e:
            logger.warning(f"Neo4j connection failed: {e} - continuing without graph updates")
            self.neo4j_driver = None
        
        # Connect to Redis
        try:
            logger.info(f"Connecting to Redis at {REDIS_URL}...")
            self.redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            await self.redis_client.ping()
            logger.info("Redis connected")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            raise
        
        # Initialize detection modules
        db_adapter = DatabaseAdapter(self.db_pool)
        neo4j_adapter = Neo4jAdapter(self.neo4j_driver) if self.neo4j_driver else None
        
        # Create sync Redis adapter for matcher
        redis_adapter = RedisAdapter(self.redis_client)
        
        self.cabal_engine = CabalCorrelationEngine(
            db_client=db_adapter,
            neo4j_client=neo4j_adapter
        )
        
        # Initialize Fresh Wallet Matcher for CEX withdrawal correlation
        self.fresh_matcher = CEXFreshWalletMatcher(
            redis_client=redis_adapter,
            db_client=db_adapter,
            neo4j_client=neo4j_adapter,
        )
        self.telegram = TelegramNotifier()
        logger.info("Fresh Wallet Matcher enabled")
        
        self.influencer_monitor = InfluencerMonitor(
            db=db_adapter
        )
        await self.influencer_monitor.refresh_whitelist()
        
        logger.info("Detection modules initialized")
        
        # Initialize execution layer
        try:
            if self.auto_execute:
                # 1. Create shared HTTP session
                self._aio_session = aiohttp.ClientSession()
                http_adapter = HttpClientAdapter(self._aio_session)
                rpc_adapter_sol = RpcClientAdapter(SOLANA_RPC_URL, self._aio_session)
                
                # 2. Key Management
                key_manager = AESKeyManager(KEY_ENCRYPTION_SECRET)
                
                # 3. Sub-wallet Management
                subwallet_manager = SubWalletManager(
                    db_client=db_adapter,
                    key_manager=key_manager
                )
                
                # 4. Risk & Execution Components
                self.circuit_breaker = CircuitBreaker(
                    db_client=db_adapter,
                    capital=float(TRADING_CAPITAL)
                )
                self.jupiter_client = JupiterClient(session=self._aio_session)
                
                # 5. Jito & Simulator
                jito_submitter = JitoBundleSubmitter(http_client=http_adapter)
                token_simulator = TokenSimulator(
                    http_client=http_adapter,
                    rpc_client=rpc_adapter_sol,
                    db_client=db_adapter
                )
                
                # 6. Orchestrator
                self.orchestrator = ExecutionOrchestrator(
                    simulator=token_simulator,
                    circuit_breaker=self.circuit_breaker,
                    router=self.jupiter_client,
                    subwallet_manager=subwallet_manager,
                    jito=jito_submitter,
                    db_client=db_adapter,
                    capital=float(TRADING_CAPITAL),
                )
                
                if self.dry_run:
                    logger.info("Execution layer initialized (DRY RUN MODE)")
                else:
                    logger.info("Execution layer initialized (LIVE TRADING)")
            else:
                logger.info("Auto-execution DISABLED (alerts only)")
        except Exception as e:
            logger.error(f"Failed to initialize execution layer: {e}")
            logger.info("Continuing without automated execution...")
            self.auto_execute = False
        
        # Notify dashboard
        try:
            await self.publish_alert("system", {
                "message": f"Logic Engine started - Auto-execute: {self.auto_execute}"
            })
        except Exception as e:
            logger.warning(f"Could not publish startup alert: {e}")
        
        # Start processing loop
        self._running = True
        await self._process_loop()
    
    async def _process_loop(self):
        """Main event processing loop."""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("solana:transactions", "solana:alerts", "solana:cex_withdrawals")
        
        logger.info("Listening for events...")
        logger.info("   Channels: transactions, alerts, cex_withdrawals")
        
        async for message in pubsub.listen():
            if not self._running:
                break
                
            if message["type"] != "message":
                continue
            
            try:
                channel = message["channel"]
                data = json.loads(message["data"])
                
                logger.debug(f"Received message from Redis on channel: {channel}")
                
                if channel == "solana:transactions":
                    await self._process_transaction(data)
                elif channel == "solana:cex_withdrawals":
                    logger.info(f"Incoming CEX withdrawal detected: {data.get('tx_hash', 'unknown')}")
                    await self._process_cex_withdrawal(data)
                elif channel == "solana:alerts":
                    # Handle system alerts/feedback
                    pass
                    
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    
    async def _process_transaction(self, tx_data: dict):
        """Process a transaction through all detection modules."""
        
        # Convert to correlation event
        event = CorrelationEvent(
            wallet_address=tx_data.get("from_wallet", "unknown"),
            contract_address=tx_data.get("token_mint", tx_data.get("tx_hash", "")),
            slot=tx_data.get("slot", 0),
            tx_hash=tx_data.get("tx_hash", ""),
            timestamp=datetime.now(timezone.utc),
            amount=tx_data.get("amount"),
            action="swap" if tx_data.get("has_swap", False) else "transfer"
        )
        
        # Persist event to tx_events for cabal correlation queries
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO tx_events (
                        wallet_address, program_id, tx_hash, slot, event_time, action
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT DO NOTHING
                """,
                    event.wallet_address,
                    event.contract_address,
                    event.tx_hash,
                    event.slot,
                    event.timestamp,
                    event.action
                )
        except Exception as e:
            logger.debug(f"tx_events insert skipped: {e}")
        
        # 1. Run Cabal Detection
        try:
            results = await self.cabal_engine.process_event(event)
            
            for result in results:
                if result.is_cabal:
                    # Cabal detected!
                    await self.publish_alert("cabal", {
                        "group_name": f"Cluster_{result.cluster_id[:8]}",
                        "wallet_count": result.wallet_count,
                        "confidence": float(result.confidence),
                        "contract": result.contract_address,
                        "message": f"Cabal detected! {result.wallet_count} coordinated wallets"
                    })
                    logger.info(f"🔥 CABAL DETECTED: {result.wallet_count} wallets, conf={result.confidence:.2f}")
                    
                    # Auto-execute if enabled and meets confidence threshold
                    if self.auto_execute and should_execute(SignalType.CABAL, result.confidence):
                        await self._execute_signal(
                            source=SignalSource.CABAL,
                            source_id=result.cluster_id,
                            token_mint=result.contract_address,
                            confidence=result.confidence,
                        )
        except Exception as e:
            logger.debug(f"Cabal engine error: {e}")
        
        # 2. Fresh Wallet Check is skipped for now (needs CEX withdrawal stream)
        # The CEXFreshWalletMatcher processes CEX withdrawals, not regular swaps
        
        # 3. Check Influencer Activity
        try:
            # Pass raw transaction data to allow monitor to determine buy/sell logic
            signal = await self.influencer_monitor.process_event({
                "wallet_address": tx_data.get("from_wallet"),
                "token_in": tx_data.get("token_in"),
                "token_out": tx_data.get("token_out"),
                "amount_in": tx_data.get("amount_in"),
                "amount_out": tx_data.get("amount_out"),
                "program_id": tx_data.get("program_id")
            })
            
            if signal:
                await self.publish_alert("influencer", {
                    "influencer_address": signal.influencer_address,
                    "token_mint": signal.token_mint,
                    "amount_in": float(signal.amount_in),
                    "confidence": float(signal.confidence),
                    "message": f"Influencer buy: {signal.influencer_address[:8]}..."
                })
                
                # Auto-execute if enabled and meets confidence threshold
                # Get wallet category from metadata for adjusted threshold
                confidence_val = Decimal(str(signal.confidence))
                if self.auto_execute and should_execute(SignalType.INFLUENCER, confidence_val):
                    await self._execute_signal(
                        source=SignalSource.INFLUENCER,
                        source_id=signal.influencer_address,
                        token_mint=signal.token_mint,
                        confidence=confidence_val,
                    )
        except Exception as e:
            logger.debug(f"Influencer monitor error: {e}")
    
    async def _execute_signal(
        self, 
        source: SignalSource, 
        source_id: str, 
        token_mint: str, 
        confidence: Decimal
    ):
        """Execute a trade signal through the orchestrator."""
        if not self.orchestrator:
            return
        
        # Create trade signal
        signal = TradeSignal(
            source=source,
            source_id=source_id,
            token_mint=token_mint,
            confidence=confidence,
        )
        
        if self.dry_run:
            logger.info(f"🧪 DRY RUN: Would execute {source} signal for {token_mint[:8]}... (conf={confidence:.2f})")
            await self.publish_alert("execution", {
                "action": "DRY_RUN",
                "token_mint": token_mint,
                "source": source,
                "confidence": float(confidence),
                "message": f"[DRY RUN] Would buy {token_mint[:8]}..."
            })
            return
        
        # Execute the trade
        try:
            result = await self.orchestrator.process_signal(signal)
            
            if result.success:
                logger.info(f"✅ TRADE EXECUTED: {result.trade_id} | {token_mint[:8]}...")
                await self.publish_alert("execution", {
                    "action": "TRADE_EXECUTED",
                    "trade_id": result.trade_id,
                    "token_mint": token_mint,
                    "entry_price": float(result.entry_price) if result.entry_price else 0,
                    "amount_received": float(result.amount_received) if result.amount_received else 0,
                    "message": f"Bought {token_mint[:8]}..."
                })
            else:
                logger.warning(f"❌ Trade failed: {result.error}")
                await self.publish_alert("blocked", {
                    "action": "TRADE_BLOCKED",
                    "token_mint": token_mint,
                    "reason": result.error,
                    "message": f"Trade blocked: {result.error}"
                })
        except Exception as e:
            logger.error(f"Execution error: {e}")

    async def _process_cex_withdrawal(self, data: dict):
        """Process a CEX withdrawal event through the matcher."""
        logger.info(f"Processing CEX withdrawal for tx: {data.get('tx_hash', 'unknown')}")
        if not self.fresh_matcher:
            return

        try:
            # Reconstruct withdrawal from incoming data
            withdrawal = CEXWithdrawal(
                tx_hash=data["tx_hash"],
                cex_source=data["cex_source"],
                amount=Decimal(str(data["amount"])),
                decimals=data["decimals"],
                timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(timezone.utc),
                target_address=data.get("target_address")
            )

            result = await self.fresh_matcher.process_withdrawal(withdrawal)
            
            if result:
                # High confidence match found!
                await self.publish_alert("fresh_wallet", {
                    "cex_name": result.withdrawal.cex_source,
                    "recipient": result.wallet.address,
                    "amount": float(result.withdrawal.amount),
                    "amount_sol": float(result.withdrawal.amount),
                    "confidence": float(result.match_score),
                    "tx_hash": result.withdrawal.tx_hash,
                    "recipient_tx_count": result.wallet.tx_count,
                    "message": f"NEW FRESH WALLET: Matching withdrawal from {result.withdrawal.cex_source} found!"
                })

                logger.info(f"NEW FRESH WALLET MATCHED: {result.wallet.address[:8]}... from {result.withdrawal.cex_source} (Score: {result.match_score:.2f})")

                # Auto-execute if confidence meets threshold
                # Note: For fresh wallets, we usually wait for their first swap to know WHAT to buy
                # But if we have pre-flight logic or if the destination address is already interacting with a token
                if self.auto_execute and should_execute(SignalType.FRESH_WALLET, result.match_score):
                    # In a real scenario, we might track this wallet for its next swap
                    # For now, we'll log the detection
                    logger.info(f"Automated tracking enabled for fresh wallet {result.wallet.address[:8]}...")
        
        except Exception as e:
            logger.error(f"Error processing CEX withdrawal: {e}")
    
    async def publish_alert(self, alert_type: str, data: dict):
        """Publish alert to Redis for dashboard."""
        payload = {
            "type": alert_type,
            **data
        }
        await self.redis_client.publish("solana:alerts", json.dumps(payload))
        logger.info(f"Published {alert_type} alert")
        
        # Send critical alerts to Telegram
        if self.telegram and alert_type in ("cabal", "influencer", "execution", "blocked", "fresh_wallet"):
            await self.telegram.send_alert(alert_type.upper(), data)
    
    async def stop(self):
        """Gracefully shutdown."""
        self._running = False
        if self.db_pool:
            await self.db_pool.close()
        if self.neo4j_driver:
            await self.neo4j_driver.close()
        logger.info("👋 Logic Engine stopped")


class DatabaseAdapter:
    """Adapter to match the DatabaseClient protocol."""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    async def fetch(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def execute(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)


class Neo4jAdapter:
    """Adapter to match the GraphClient protocol."""
    
    def __init__(self, driver):
        self.driver = driver
    
    async def run(self, query: str, **params):
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            return [record async for record in result]


class RedisAdapter:
    """Adapter to bridge async redis client to matcher protocol."""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def setex(self, key: str, ttl: int, value: str):
        await self.redis.setex(key, ttl, value)
    
    async def get(self, key: str):
        return await self.redis.get(key)


class HttpClientAdapter:
    """Adapter to match the HttpClient protocol."""
    
    def __init__(self, session: aiohttp.ClientSession):
        self._session = session
        
    async def get(self, url: str, params: dict = None) -> dict:
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return {}
            return await resp.json()
            
    async def post(self, url: str, json: dict = None, headers: dict = None) -> dict:
        async with self._session.post(url, json=json, headers=headers) as resp:
            if resp.status != 200:
                return {}
            return await resp.json()


class RpcClientAdapter:
    """Adapter to match the RpcClient protocol."""
    
    def __init__(self, rpc_url: str, session: aiohttp.ClientSession):
        self.url = rpc_url
        self._session = session
        
    async def simulate_transaction(self, tx_bytes: bytes) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "simulateTransaction",
            "params": [base64.b64encode(tx_bytes).decode("utf-8"), {"encoding": "base64"}]
        }
        async with self._session.post(self.url, json=payload) as resp:
            res = await resp.json()
            return res.get("result", {})
            
    async def get_token_accounts(self, owner: str) -> list:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [owner, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]
        }
        async with self._session.post(self.url, json=payload) as resp:
            res = await resp.json()
            return res.get("result", {}).get("value", [])


async def main():
    engine = LogicEngine()
    try:
        await engine.start()
    except KeyboardInterrupt:
        await engine.stop()


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  SOLANA INTEL ENGINE - LOGIC LAYER")
    logger.info("=" * 60)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Shutdown requested")
