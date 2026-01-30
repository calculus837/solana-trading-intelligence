"""Configuration for the Ingestion Layer."""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class IngestionConfig:
    """Configuration for Solana ingestion layer."""
    
    # RPC Configuration
    rpc_ws_url: str = field(
        default_factory=lambda: os.getenv(
            "SOLANA_WS_URL", 
            "wss://api.mainnet-beta.solana.com"
        )
    )
    helius_api_key: str = field(
        default_factory=lambda: os.getenv("HELIUS_API_KEY", "")
    )
    
    # Redis Configuration
    redis_host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
    
    # Monitored Programs (DEX routers, bridges, etc.)
    monitored_programs: List[str] = field(default_factory=lambda: [
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM V4
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter Aggregator
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",   # Orca Whirlpool
    ])
    
    # Known CEX Hot Wallets (Solana)
    cex_hot_wallets: dict = field(default_factory=lambda: {
        # Binance
        "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance",
        "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance",
        # OKX
        "5VCwKtCXgCJ6kit5FybXjvriW3xELsFDhYrPSqtJNmaD": "OKX",
        # Coinbase
        "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS": "Coinbase",
        "2AQdpHJ2JpcEgPiATUXjQxA8QmafFegfQwSLWSprPicm": "Coinbase",
        # Bybit
        "AC5RDfQFmDS1deWZos921JfqscXdByf8BKHs5ACWjtW2": "Bybit",
    })
    
    # Tracked Wallets (Influencers) - Populated from DB at runtime normally
    tracked_wallets: List[str] = field(default_factory=list)
    
    # Reconnection settings
    max_reconnect_attempts: int = 10
    reconnect_delay_seconds: float = 1.0
    reconnect_delay_max_seconds: float = 60.0
    
    # Event processing
    batch_size: int = 100
    flush_interval_seconds: float = 1.0
    
    @property
    def helius_ws_url(self) -> str:
        """Get Helius WebSocket URL if API key is configured."""
        if self.helius_api_key:
            return f"wss://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
        return self.rpc_ws_url


# Default configuration
DEFAULT_CONFIG = IngestionConfig()
