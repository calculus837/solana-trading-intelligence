"""Solana WebSocket Listener for real-time blockchain data."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Callable, Awaitable
import backoff

try:
    from websockets import connect
    from websockets.exceptions import ConnectionClosed
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

from .config import IngestionConfig, DEFAULT_CONFIG
from .events import TransactionEvent, WithdrawalEvent, EventType
from .cex_monitor import CEXWithdrawalMonitor
from .publisher import RedisEventPublisher

logger = logging.getLogger(__name__)


class SolanaWebSocketListener:
    """
    WebSocket listener for real-time Solana blockchain data.
    
    Subscribes to:
    - Account changes for monitored programs
    - Transaction logs for CEX wallet monitoring
    - Slot notifications for timing
    
    Integrates with CEXWithdrawalMonitor for fresh wallet detection
    and RedisEventPublisher for downstream event streaming.
    """
    
    def __init__(
        self,
        publisher: RedisEventPublisher,
        config: IngestionConfig = DEFAULT_CONFIG,
        cex_monitor: Optional[CEXWithdrawalMonitor] = None,
    ):
        """
        Initialize the WebSocket listener.
        
        Args:
            publisher: Redis event publisher for downstream events
            config: Ingestion configuration
            cex_monitor: CEX withdrawal monitor (created if not provided)
        """
        if not HAS_WEBSOCKETS:
            raise ImportError("websockets package required. Install with: pip install websockets")
        
        self.publisher = publisher
        self.config = config
        self.cex_monitor = cex_monitor or CEXWithdrawalMonitor(config)
        
        self._ws = None
        self._running = False
        self._subscription_ids: dict[str, int] = {}
        self._message_count = 0
        self._event_handlers: list[Callable[[TransactionEvent], Awaitable[None]]] = []
        self._withdrawal_handlers: list[Callable[[WithdrawalEvent], Awaitable[None]]] = []
    
    def on_transaction(
        self, 
        handler: Callable[[TransactionEvent], Awaitable[None]]
    ) -> None:
        """Register a handler for transaction events."""
        self._event_handlers.append(handler)
    
    def on_withdrawal(
        self, 
        handler: Callable[[WithdrawalEvent], Awaitable[None]]
    ) -> None:
        """Register a handler for CEX withdrawal events."""
        self._withdrawal_handlers.append(handler)
    
    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_time=300,
        on_backoff=lambda details: logger.warning(
            f"WebSocket reconnecting... attempt {details['tries']}"
        ),
    )
    async def start(self) -> None:
        """
        Start the WebSocket listener.
        
        Connects to the Solana RPC WebSocket endpoint and subscribes
        to configured programs and accounts. Automatically reconnects
        on connection loss.
        """
        self._running = True
        ws_url = self.config.helius_ws_url
        
        logger.info(f"Connecting to Solana WebSocket: {ws_url[:50]}...")
        
        async with connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            self._ws = ws
            logger.info("WebSocket connected successfully")
            
            # Subscribe to monitored programs
            await self._subscribe_to_programs()
            
            # Subscribe to CEX wallet accounts
            await self._subscribe_to_cex_wallets()

            # Subscribe to Influencer/Tracked Wallets
            await self._subscribe_to_tracked_wallets()
            
            # Main message loop
            await self._message_loop()
    
    async def stop(self) -> None:
        """Stop the WebSocket listener gracefully."""
        self._running = False
        if self._ws:
            await self._ws.close()
            logger.info("WebSocket connection closed")
    
    async def _subscribe_to_programs(self) -> None:
        """Subscribe to logs for monitored programs."""
        for program_id in self.config.monitored_programs:
            request = {
                "jsonrpc": "2.0",
                "id": f"prog_{program_id[:8]}",
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [program_id]},
                    {"commitment": "confirmed"}
                ]
            }
            await self._ws.send(json.dumps(request))
            logger.info(f"Subscribed to program logs: {program_id[:16]}...")
    
    async def _subscribe_to_cex_wallets(self) -> None:
        """Subscribe to account changes for CEX hot wallets."""
        for wallet_address, exchange_name in self.cex_monitor.cex_wallets.items():
            request = {
                "jsonrpc": "2.0",
                "id": f"cex_{wallet_address[:8]}",
                "method": "accountSubscribe",
                "params": [
                    wallet_address,
                    {"encoding": "jsonParsed", "commitment": "confirmed"}
                ]
            }
            await self._ws.send(json.dumps(request))
            logger.debug(f"Subscribed to CEX wallet: {exchange_name} ({wallet_address[:16]}...)")
        
        logger.info(f"Subscribed to {len(self.cex_monitor.cex_wallets)} CEX wallets")

    async def _subscribe_to_tracked_wallets(self) -> None:
        """Subscribe to logs for tracked wallets (Influencers)."""
        # In a real app, this list comes from the DB or config.
        # For now, we assume config might have it or we load it here.
        # Ideally, we'd inject a list of influencers.
        
        # Checking if config has 'tracked_wallets' (it doesn't yet).
        # We will dynamically check or use a placeholder if not present.
        tracked = getattr(self.config, 'tracked_wallets', [])
        
        for address in tracked:
            request = {
                "jsonrpc": "2.0",
                "id": f"inf_{address[:8]}", # ID prefix 'inf_' helps identify source
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [address]},
                    {"commitment": "confirmed"}
                ]
            }
            await self._ws.send(json.dumps(request))
            logger.info(f"Subscribed to influencer logs: {address[:16]}...")
    
    async def _message_loop(self) -> None:
        """Main message processing loop."""
        try:
            async for message in self._ws:
                if not self._running:
                    break
                
                self._message_count += 1
                
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {message[:100]}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    
        except ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}")
            if self._running:
                raise  # Trigger reconnection via backoff
    
    async def _process_message(self, data: dict) -> None:
        """Process a WebSocket message."""
        # Handle subscription confirmations
        if "result" in data and "id" in data:
            sub_id = data.get("id", "")
            self._subscription_ids[sub_id] = data["result"]
            logger.debug(f"Subscription confirmed: {sub_id}")
            return
        
        # Handle notifications
        if "method" not in data:
            return
        
        method = data["method"]
        params = data.get("params", {})
        
        if method == "logsNotification":
            await self._handle_logs_notification(params)
        elif method == "accountNotification":
            await self._handle_account_notification(params)
    
    async def _handle_logs_notification(self, params: dict) -> None:
        """Handle a logs notification (program activity)."""
        result = params.get("result", {})
        value = result.get("value", {})
        
        signature = value.get("signature")
        logs = value.get("logs", [])
        err = value.get("err")
        
        if err:
            return  # Skip failed transactions
        
        # Create transaction event
        event = TransactionEvent(
            event_type=EventType.PROGRAM_INTERACTION,
            tx_hash=signature,
            slot=result.get("context", {}).get("slot", 0),
            timestamp=datetime.now(timezone.utc),
            wallet_address="",  # Would need to parse from logs
            program_id=self._extract_program_from_logs(logs),
        )
        
        # Publish and notify handlers
        await self.publisher.publish_transaction(event)
        for handler in self._event_handlers:
            await handler(event)
    
    async def _handle_account_notification(self, params: dict) -> None:
        """Handle an account notification (balance change)."""
        result = params.get("result", {})
        value = result.get("value", {})
        
        # This would require parsing the transaction that caused
        # the balance change - for now, log the activity
        lamports = value.get("lamports", 0)
        slot = result.get("context", {}).get("slot", 0)
        
        logger.debug(f"Account balance change detected in slot {slot}: {lamports} lamports")
    
    def _extract_program_from_logs(self, logs: list) -> Optional[str]:
        """Extract program ID from transaction logs."""
        for log in logs:
            if "Program" in log and "invoke" in log:
                # Format: "Program <program_id> invoke [1]"
                parts = log.split()
                if len(parts) >= 2:
                    return parts[1]
        return None
    
    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self._ws is not None and self._ws.open
    
    @property
    def message_count(self) -> int:
        """Get total number of messages processed."""
        return self._message_count


async def run_ingestion(
    redis_client,
    config: IngestionConfig = DEFAULT_CONFIG,
) -> None:
    """
    Main entry point for running the ingestion layer.
    
    Args:
        redis_client: Async Redis client
        config: Ingestion configuration
    """
    publisher = RedisEventPublisher(redis_client)
    listener = SolanaWebSocketListener(publisher, config)
    
    logger.info("Starting Solana Ingestion Layer...")
    
    try:
        await listener.start()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        await listener.stop()
        logger.info("Ingestion Layer stopped")
