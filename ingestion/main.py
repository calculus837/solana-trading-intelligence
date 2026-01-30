import asyncio
import json
import logging
import os
import backoff
from websockets import connect
from dotenv import load_dotenv
from redis import Redis

load_dotenv()

# Configuration
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Determine the best WebSocket URL based on available credentials
def get_websocket_url() -> str:
    """
    Returns the optimal WebSocket URL based on available API keys.
    Priority: Helius > Public RPC
    """
    if HELIUS_API_KEY and HELIUS_API_KEY != "your_helius_key_here":
        # Helius Enhanced WebSocket - better reliability and parsing
        return f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    else:
        # Fallback to public RPC (rate limited, slower)
        return os.getenv("SOLANA_WS_URL", "wss://api.mainnet-beta.solana.com")

SOLANA_WS_URL = get_websocket_url()

# Tracked programs (DEX routers for swap detection)
MONITORED_PROGRAMS = [
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM V4
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter V6
    "whirLbMiicVdio4qvUoxLcnyxs9M555azC4ZRNg272reQC2PrVm",  # Orca Whirlpool
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",   # Pump.fun
]

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log which data source we're using
if "helius" in SOLANA_WS_URL.lower():
    logger.info("🚀 Using HELIUS Enhanced WebSocket (production-grade)")
else:
    logger.warning("⚠️ Using PUBLIC RPC (rate-limited). Set HELIUS_API_KEY for better performance.")


redis_client = Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

# Import CEX monitor for fresh wallet detection
from .cex_monitor import CEXWithdrawalMonitor
from .config import DEFAULT_CONFIG

# Initialize CEX withdrawal monitor
cex_monitor = CEXWithdrawalMonitor(config=DEFAULT_CONFIG)

def publish_alert(alert_type: str, data: dict):
    """Publish alert to Redis channel for dashboard."""
    payload = {
        "type": alert_type,
        **data
    }
    redis_client.publish("solana:alerts", json.dumps(payload))
    logger.info(f"📤 Published alert: {alert_type}")

def publish_transaction(data: dict):
    """Publish transaction to Redis channel."""
    redis_client.publish("solana:transactions", json.dumps(data))

def publish_cex_withdrawal(withdrawal_event):
    """Publish CEX withdrawal to Redis for Fresh Wallet Forensics."""
    payload = {
        "tx_hash": withdrawal_event.tx_hash,
        "cex_source": withdrawal_event.cex_name,
        "amount": float(withdrawal_event.amount_sol),
        "decimals": withdrawal_event.decimals,
        "target_address": withdrawal_event.recipient,
        "recipient_tx_count": withdrawal_event.recipient_tx_count,
        "slot": withdrawal_event.slot,
        "timestamp": withdrawal_event.timestamp.isoformat() if withdrawal_event.timestamp else None,
    }
    redis_client.publish("solana:cex_withdrawals", json.dumps(payload))
    logger.info(f"💸 CEX Withdrawal: {withdrawal_event.cex_name} → {withdrawal_event.recipient[:8]}... | {withdrawal_event.amount_sol:.2f} SOL")

@backoff.on_exception(backoff.expo, Exception, max_tries=None, max_time=None)
async def listen_to_mempool():
    """
    Subscribes to Solana's logs/program notifications.
    """
    logger.info(f"🔌 Connecting to: {SOLANA_WS_URL[:50]}...")
    
    async with connect(SOLANA_WS_URL) as ws:
        logger.info("✅ WebSocket connected!")
        
        # Subscribe to DEX program logs
        for program in MONITORED_PROGRAMS:
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [program]},
                    {"commitment": "processed"}
                ]
            }))
            logger.info(f"📡 Subscribed to DEX: {program[:16]}...")
        
        # Subscribe to CEX hot wallet addresses for fresh wallet forensics
        cex_wallets = cex_monitor.get_monitored_wallets()
        for address in cex_wallets:
            exchange = cex_monitor.get_exchange_name(address)
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [address]},
                    {"commitment": "processed"}
                ]
            }))
            logger.info(f"💰 Subscribed to CEX: {exchange} ({address[:8]}...)")
        
        logger.info(f"📊 Monitoring {len(cex_wallets)} CEX hot wallets")
        
        # Notify dashboard we're connected
        publish_alert("system", {
            "message": "Ingestion layer connected to Solana",
            "programs": len(MONITORED_PROGRAMS),
            "cex_wallets": len(cex_wallets)
        })
        
        async for message in ws:
            data = json.loads(message)
            
            if "method" in data and data["method"] == "logsNotification":
                await process_log_notification(data["params"]["result"])
            elif "result" in data:
                # Subscription confirmation
                logger.debug(f"Subscription confirmed: {data['result']}")

async def process_log_notification(result):
    """Process log notification and publish to dashboard."""
    try:
        value = result.get("value", {})
        signature = value.get("signature", "unknown")
        logs = value.get("logs", [])
        slot = result.get("context", {}).get("slot", 0)
        
        # Check for swap/trade activity
        is_swap = any("Swap" in log or "swap" in log for log in logs)
        is_transfer = any("Transfer" in log for log in logs)
        
        # Extract wallet addresses from logs (simplified - real impl would decode properly)
        wallets = extract_addresses_from_logs(logs)
        token_mint = extract_token_mint(logs)
        
        # Check for CEX withdrawals (Fresh Wallet Forensics)
        for wallet in wallets:
            if cex_monitor.is_cex_wallet(wallet):
                # This could be a CEX withdrawal!
                # Find recipient (first non-CEX wallet in the list)
                recipients = [w for w in wallets if w != wallet and not cex_monitor.is_cex_wallet(w)]
                if recipients:
                    recipient = recipients[0]
                    # Use parse_transfer to create withdrawal event
                    withdrawal = cex_monitor.parse_transfer(
                        tx_hash=signature,
                        slot=slot,
                        from_address=wallet,
                        to_address=recipient,
                        amount_lamports=0,  # Will be enriched by RPC if needed
                        recipient_tx_count=0,  # Would need RPC call
                        timestamp=None
                    )
                    if withdrawal:
                        publish_cex_withdrawal(withdrawal)
        
        if is_swap:
            # This is a DEX trade!
            publish_alert("execution", {
                "action": "SWAP_DETECTED",
                "tx_hash": signature,
                "logs": logs[:3],
                "message": f"Swap detected: {signature[:16]}..."
            })
        
        # Publish enriched transaction data for logic engine
        publish_transaction({
            "tx_hash": signature,
            "slot": slot,
            "has_swap": is_swap,
            "has_transfer": is_transfer,
            "log_count": len(logs),
            "from_wallet": wallets[0] if wallets else "unknown",
            "token_mint": token_mint,
            "timestamp": int(asyncio.get_event_loop().time())
        })
        
    except Exception as e:
        logger.error(f"Error processing notification: {e}")

def extract_addresses_from_logs(logs: list) -> list:
    """Extract Solana addresses from log lines (simplified)."""
    import re
    # Solana addresses are base58, 32-44 chars
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    addresses = []
    for log in logs[:10]:  # Limit to first 10 logs
        matches = re.findall(pattern, str(log))
        addresses.extend(matches[:3])  # Max 3 per log
    return list(set(addresses))[:5]  # Return max 5 unique

def extract_token_mint(logs: list) -> str:
    """Try to extract token mint from logs."""
    for log in logs:
        if "mint" in log.lower():
            # Try to find an address after "mint"
            import re
            match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', str(log))
            if match:
                return match.group(0)
    return ""


if __name__ == "__main__":
    logger.info("🚀 Starting Solana Ingestion Layer...")
    logger.info(f"📡 Target: {SOLANA_WS_URL[:50]}...")
    logger.info(f"📊 Redis: {REDIS_HOST}:{REDIS_PORT}")
    
    try:
        asyncio.run(listen_to_mempool())
    except KeyboardInterrupt:
        logger.info("👋 Ingestion Layer stopped.")

