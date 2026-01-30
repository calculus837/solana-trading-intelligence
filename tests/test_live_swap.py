"""
Live Swap Test - End-to-end test of the execution pipeline.

This script performs a real swap on Solana mainnet using Jupiter.
Requires a funded wallet with SOL.

Usage:
    # Dry run (quote only, no actual swap)
    python -m tests.test_live_swap --dry-run
    
    # Live swap (requires funded wallet)
    python -m tests.test_live_swap --live --amount 0.001
"""

import argparse
import asyncio
import base64
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiohttp
from dotenv import load_dotenv

from execution.jupiter_client import JupiterClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()


async def test_quote_only(amount_sol: float):
    """Test getting a quote without executing."""
    logger.info(f"Testing quote for {amount_sol} SOL -> USDC...")
    
    amount_lamports = int(amount_sol * 1e9)
    
    async with JupiterClient() as client:
        quote = await client.get_quote(
            input_mint=JupiterClient.SOL_MINT,
            output_mint=JupiterClient.USDC_MINT,
            amount=amount_lamports,
            slippage_bps=50,
        )
        
        if quote:
            usdc_amount = quote.out_amount / 1e6  # USDC has 6 decimals
            logger.info(f"✅ Quote received:")
            logger.info(f"   Input:  {amount_sol} SOL")
            logger.info(f"   Output: {usdc_amount:.4f} USDC")
            logger.info(f"   Price Impact: {quote.price_impact_pct:.4f}%")
            return True
        else:
            logger.error("❌ Failed to get quote")
            return False


async def test_live_swap(amount_sol: float, private_key_b58: str):
    """Execute a real swap on mainnet."""
    try:
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction
    except ImportError:
        logger.error("❌ solders package required. Install with: pip install solders")
        return False
    
    logger.info(f"🚀 Executing LIVE swap: {amount_sol} SOL -> USDC...")
    logger.warning("⚠️  This will spend real SOL!")
    
    # Load keypair
    try:
        # Try base58 format first
        keypair = Keypair.from_base58_string(private_key_b58)
    except Exception:
        try:
            # Try JSON array format
            import json
            key_bytes = bytes(json.loads(private_key_b58))
            keypair = Keypair.from_bytes(key_bytes)
        except Exception as e:
            logger.error(f"❌ Failed to parse private key: {e}")
            return False
    
    pubkey = str(keypair.pubkey())
    logger.info(f"Wallet: {pubkey}")
    
    amount_lamports = int(amount_sol * 1e9)
    
    async with JupiterClient() as client:
        # Step 1: Get quote
        logger.info("Step 1/3: Getting quote...")
        quote = await client.get_quote(
            input_mint=JupiterClient.SOL_MINT,
            output_mint=JupiterClient.USDC_MINT,
            amount=amount_lamports,
            slippage_bps=100,  # 1% slippage for safety
        )
        
        if not quote:
            logger.error("❌ Failed to get quote")
            return False
            
        usdc_amount = quote.out_amount / 1e6
        logger.info(f"   Quote: {amount_sol} SOL -> {usdc_amount:.4f} USDC")
        
        # Step 2: Get swap transaction
        logger.info("Step 2/3: Building transaction...")
        tx_bytes = await client.get_swap_transaction(
            quote=quote,
            user_public_key=pubkey,
            priority_fee_lamports=50000,  # 0.00005 SOL priority fee
        )
        
        if not tx_bytes:
            logger.error("❌ Failed to get swap transaction")
            return False
            
        logger.info(f"   Transaction size: {len(tx_bytes)} bytes")
        
        # Step 3: Sign and send
        logger.info("Step 3/3: Signing and sending...")
        
        # Deserialize the transaction
        tx = VersionedTransaction.from_bytes(tx_bytes)
        
        # Sign with our keypair
        tx.sign([keypair])
        
        # Send to RPC
        rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    base64.b64encode(bytes(tx)).decode(),
                    {"encoding": "base64", "skipPreflight": False}
                ]
            }
            
            async with session.post(rpc_url, json=payload) as response:
                result = await response.json()
                
            if "error" in result:
                logger.error(f"❌ Transaction failed: {result['error']}")
                return False
                
            signature = result.get("result")
            logger.info(f"✅ Transaction sent!")
            logger.info(f"   Signature: {signature}")
            logger.info(f"   View on Solscan: https://solscan.io/tx/{signature}")
            
            return True


async def main():
    parser = argparse.ArgumentParser(description="Test live swap execution")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only get quote, don't execute swap"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute real swap (requires PRIVATE_KEY in .env)"
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=0.001,
        help="Amount of SOL to swap (default: 0.001)"
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        success = await test_quote_only(args.amount)
    elif args.live:
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            logger.error("❌ PRIVATE_KEY not found in .env file")
            logger.error("   Add: PRIVATE_KEY=your_base58_private_key")
            return
        success = await test_live_swap(args.amount, private_key)
    else:
        logger.info("No action specified. Use --dry-run or --live")
        logger.info("  --dry-run: Test quote without spending")
        logger.info("  --live:    Execute real swap")
        return
        
    if success:
        logger.info("✅ Test completed successfully!")
    else:
        logger.error("❌ Test failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
