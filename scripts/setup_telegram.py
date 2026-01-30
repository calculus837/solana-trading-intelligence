"""
Telegram Setup Helper

This script helps you verify your Telegram Bot configuration.
Prerequisites:
1. Create a bot via @BotFather to get your TOKEN.
2. Send a message to your bot.
3. Visit https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates to find your Chat ID.

Usage:
    python scripts/setup_telegram.py
"""

import asyncio
import aiohttp
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

async def verify_telegram(token, chat_id):
    logger.info(f"Testing Telegram config...")
    logger.info(f"Token: {token[:6]}...{token[-4:]}")
    logger.info(f"Chat ID: {chat_id}")
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "🚨 <b>Solana Intel Engine</b>: Test Alert\n\nYour Telegram integration is working! ✅",
        "parse_mode": "HTML"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info("✅ SUCCESS! Message sent.")
                    logger.info(f"Message ID: {data['result']['message_id']}")
                    return True
                else:
                    logger.error(f"❌ FAILED. HTTP {resp.status}")
                    logger.error(await resp.text())
                    return False
        except Exception as e:
            logger.error(f"❌ Connection Error: {e}")
            return False

if __name__ == "__main__":
    print("\n=== Telegram Notification Setup ===\n")
    print("To enable alerts, you need a Bot Token and Chat ID.")
    print("1. Open Telegram and search for @BotFather")
    print("2. Send /newbot and follow instructions to get your HTTP API Token")
    print("3. Start a chat with your new bot and send 'Hello'")
    print("4. Get your Chat ID (you can use @userinfobot or curl getUpdates)")
    print("\n-----------------------------------")
    
    token = input("Enter Bot Token: ").strip()
    chat_id = input("Enter Chat ID: ").strip()
    
    if token and chat_id:
        asyncio.run(verify_telegram(token, chat_id))
        print("\nIf you received the message, update your .env file:")
        print(f"TELEGRAM_BOT_TOKEN={token}")
        print(f"TELEGRAM_CHAT_ID={chat_id}")
    else:
        print("Skipping verification.")
