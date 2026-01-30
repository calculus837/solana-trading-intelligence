"""Redis Event Publisher for the Ingestion Layer."""

import asyncio
import json
import logging
from typing import Union, List
from dataclasses import dataclass

from .events import TransactionEvent, WithdrawalEvent, EventType

logger = logging.getLogger(__name__)


class RedisClientProtocol:
    """Protocol for async Redis client."""
    async def publish(self, channel: str, message: str) -> int: ...
    async def lpush(self, key: str, *values: str) -> int: ...
    async def setex(self, key: str, ttl: int, value: str) -> None: ...


@dataclass
class RedisChannels:
    """Redis channel/key names for different event types."""
    
    # Pub/Sub channels
    TRANSACTIONS: str = "solana:transactions"
    CEX_WITHDRAWALS: str = "solana:cex_withdrawals"
    FRESH_WALLETS: str = "solana:fresh_wallets"
    ALERTS: str = "solana:alerts"
    
    # List keys for batch processing
    TX_QUEUE: str = "queue:transactions"
    WITHDRAWAL_QUEUE: str = "queue:withdrawals"
    
    # Cache keys
    WITHDRAWAL_CACHE_PREFIX: str = "cache:withdrawal:"


class RedisEventPublisher:
    """
    Publishes ingestion events to Redis for downstream processing.
    
    Uses both Pub/Sub for real-time streaming and Lists for reliable
    queue-based processing.
    """
    
    def __init__(self, redis_client: RedisClientProtocol):
        """
        Initialize the publisher.
        
        Args:
            redis_client: Async Redis client instance
        """
        self.redis = redis_client
        self.channels = RedisChannels()
        self._batch: List[str] = []
        self._batch_lock = asyncio.Lock()
    
    async def publish_transaction(self, event: TransactionEvent) -> None:
        """
        Publish a transaction event to Redis.
        
        Args:
            event: The transaction event to publish
        """
        try:
            message = event.to_json()
            
            # Publish to real-time channel
            await self.redis.publish(self.channels.TRANSACTIONS, message)
            
            # Also push to queue for reliable processing
            await self.redis.lpush(self.channels.TX_QUEUE, message)
            
            logger.debug(f"Published transaction: {event.tx_hash[:16]}...")
            
        except Exception as e:
            logger.error(f"Failed to publish transaction event: {e}")
            raise
    
    async def publish_withdrawal(self, event: WithdrawalEvent) -> None:
        """
        Publish a CEX withdrawal event to Redis.
        
        This also caches the withdrawal for matching by the Fresh Wallet Matcher.
        
        Args:
            event: The withdrawal event to publish
        """
        try:
            message = event.to_json()
            
            # Publish to real-time channel
            await self.redis.publish(self.channels.CEX_WITHDRAWALS, message)
            
            # Push to queue for reliable processing
            await self.redis.lpush(self.channels.WITHDRAWAL_QUEUE, message)
            
            # Cache for matcher lookup (5 minute TTL)
            cache_key = f"{self.channels.WITHDRAWAL_CACHE_PREFIX}{event.tx_hash}"
            await self.redis.setex(cache_key, 360, message)
            
            logger.info(
                f"Published CEX withdrawal: {event.cex_name} -> "
                f"{event.recipient_wallet[:16]}... ({event.amount} SOL)"
            )
            
            # If this is a fresh wallet funding, also publish to fresh wallets channel
            if event.is_fresh_wallet_funding:
                await self.redis.publish(self.channels.FRESH_WALLETS, message)
                logger.info(f"Fresh wallet detected: {event.recipient_wallet[:16]}...")
            
        except Exception as e:
            logger.error(f"Failed to publish withdrawal event: {e}")
            raise
    
    async def publish_alert(self, alert_type: str, data: dict) -> None:
        """
        Publish an alert to the alerts channel.
        
        Args:
            alert_type: Type of alert (e.g., "high_value_transfer", "whale_activity")
            data: Alert payload
        """
        try:
            message = json.dumps({
                "type": alert_type,
                "data": data,
            })
            await self.redis.publish(self.channels.ALERTS, message)
            logger.info(f"Published alert: {alert_type}")
            
        except Exception as e:
            logger.error(f"Failed to publish alert: {e}")
    
    async def batch_publish(
        self, 
        events: List[Union[TransactionEvent, WithdrawalEvent]]
    ) -> int:
        """
        Publish a batch of events efficiently.
        
        Args:
            events: List of events to publish
            
        Returns:
            Number of events published
        """
        count = 0
        async with self._batch_lock:
            for event in events:
                try:
                    if isinstance(event, WithdrawalEvent):
                        await self.publish_withdrawal(event)
                    else:
                        await self.publish_transaction(event)
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to publish event in batch: {e}")
        
        return count
