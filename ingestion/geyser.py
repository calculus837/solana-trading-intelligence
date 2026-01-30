"""Yellowstone Geyser gRPC Client for High-Performance Ingestion.

This module provides a gRPC client to consume high-throughput streaming data 
directly from Solana validators, bypassing standard RPC polling/WebSockets 
for sub-200ms latency.
"""

import logging
import asyncio
from typing import Optional, List, Callable, Awaitable
from dataclasses import dataclass
import ssl

import grpc
from yellowstone_grpc import GeyserGrpcClient
from yellowstone_grpc.proto.geyser_pb2 import (
    SubscribeRequest,
    SubscribeRequestFilterTransactions,
    SubscribeUpdate,
    SubscribeUpdateTransaction,
)

from .publisher import RedisEventPublisher
from .cex_monitor import CEXWithdrawalMonitor

logger = logging.getLogger(__name__)


@dataclass
class ProgramFilter:
    """Filter configuration for a specific program."""
    program_id: str
    label: str


class SolanaGeyserListener:
    """
    High-performance gRPC listener for Solana Geyser streams.
    
    Why this is faster than WebSockets:
    1. Binary format (Protobuf) instead of JSON
    2. Streaming connection directly to validator/Geyser plugin
    3. Push-based model with lower overhead
    """
    
    def __init__(
        self, 
        endpoint: str, 
        token: Optional[str],
        publisher: RedisEventPublisher,
        cex_monitor: CEXWithdrawalMonitor
    ):
        """
        Initialize the Geyser listener.
        
        Args:
            endpoint: gRPC endpoint URL (e.g., http://grpc.mainnet.helius-rpc.com:10000)
            token: Authentication token (x-token)
            publisher: Redis event publisher
            cex_monitor: CEX withdrawal monitor
        """
        self.endpoint = endpoint
        self.token = token
        self.publisher = publisher
        self.cex_monitor = cex_monitor
        self._running = False
        self._client: Optional[GeyserGrpcClient] = None
        
        # Programs to monitor (same as WebSocket listener)
        self.programs = [
            ProgramFilter("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", "raydium_liquidity_pool_v4"),
            ProgramFilter("JUP6LkbZbjS1jKKwapdHNy745k03MoA5zFC720Dem6f", "jupiter_v6"),
            ProgramFilter("whirLbMiicVdio4qvU3M555azC4ZRNg272reQC2PrVm", "orca_whirlpool"),
            ProgramFilter("PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqXVg660u9f3Gn", "phoenix_v1"),
            ProgramFilter("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P", "pump_fun"),
        ]
    
    async def start(self) -> None:
        """Start consumption loop."""
        self._running = True
        logger.info(f"⚡ Starting Geyser gRPC listener on {self.endpoint}...")
        
        while self._running:
            try:
                # Initialize client
                # Note: yellowstone-grpc-client handles the channel creation internally
                self._client = GeyserGrpcClient(self.endpoint, self.token)
                
                # Build subscription request
                request = self._build_subscription_request()
                
                # Subscribe stream
                stream = self._client.subscribe()
                
                # Send initial request
                await stream.send(request)
                
                logger.info("✅ Geyser stream connected")
                
                # Process updates
                async for update in stream:
                    if not self._running:
                        break
                    
                    if update.transaction:
                        await self._process_transaction(update.transaction)
                        
            except grpc.RpcError as e:
                logger.error(f"❌ Geyser gRPC error: {e.details()} (code: {e.code()})")
                await asyncio.sleep(1)  # Brief backoff
            except Exception as e:
                logger.error(f"❌ Geyser internal error: {e}")
                await asyncio.sleep(5)
            finally:
                logger.warning("🔄 Geyser stream restarting...")
    
    def stop(self) -> None:
        """Stop the listener."""
        self._running = False
    
    def _build_subscription_request(self) -> SubscribeRequest:
        """Build the subscription request protobuf."""
        # Create map of filters
        tx_filters = {}
        
        # 1. Add filter for each DEX program
        for prog in self.programs:
            tx_filters[prog.label] = SubscribeRequestFilterTransactions(
                vote=False,
                failed=False,
                account_include=[prog.program_id],
            )
            
        # 2. Add filter for CEX wallets (for direct withdrawal tracking)
        # We assume CEX monitor has a list of addresses
        cex_wallets = self.cex_monitor.get_monitored_wallets()
        if cex_wallets:
            tx_filters["cex_wallets"] = SubscribeRequestFilterTransactions(
                vote=False,
                failed=False,
                account_include=cex_wallets,
            )
            
        return SubscribeRequest(
            transactions=tx_filters,
            commitment="processed",  # Fastest commitment level
        )
    
    async def _process_transaction(self, tx_update: SubscribeUpdateTransaction) -> None:
        """Decodes binary Geyser transaction and routes to monitors."""
        try:
            # 1. Basic Metadata
            signature = tx_update.transaction.signature.hex() if hasattr(tx_update.transaction, 'signature') else "unknown"
            slot = tx_update.slot
            
            # 2. Extract Transaction Details
            tx = tx_update.transaction.transaction
            meta = tx_update.transaction.meta
            
            # Identify the 'To' and 'From' for CEX Monitor
            # The message contains account_keys. Signers are always at the start.
            if hasattr(tx.message, 'account_keys'):
                account_keys = [pk.hex() for pk in tx.message.account_keys]
            else:
                # Handle legacy or alternative message formats if necessary
                account_keys = []
            
            # 3. Simple CEX Withdrawal Heuristic (Balance Change)
            # Check if a monitored CEX hot wallet is a 'signer' in this tx
            monitored_cex_wallets = self.cex_monitor.get_monitored_wallets()
            
            # We check if the sender (first account) is in our CEX list
            sender = account_keys[0] if account_keys else None
            
            if sender and sender in monitored_cex_wallets:
                # Route to CEX Monitor for deep logic (Amount/Freshness check)
                # We assume CEX monitor is updated to handle this direct call
                # For now, we simulate the 'events' it expects or call a specialized method
                await self.cex_monitor.process_high_speed_withdrawal(
                    signature=signature,
                    sender=sender,
                    meta=meta,
                    account_keys=account_keys
                )

            # 4. Route All Transactions to Redis for the Cabal Engine
            # We publish a minimal event to keep Redis throughput high
            payload = {
                "sig": signature,
                "slot": slot,
                "accounts": account_keys,
                "err": meta.err.err if meta.err else None
            }
            
            # Use fire-and-forget for speed
            asyncio.create_task(self.publisher.publish("solana:transactions", payload))
            
        except Exception as e:
            logger.error(f"Error processing Geyser transaction: {e}")
