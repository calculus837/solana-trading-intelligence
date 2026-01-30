
import os
import logging
import aiohttp
import asyncio

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Sends alerts to a Telegram chat using the Bot API.
    """
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if self.enabled:
            logger.info("Telegram notifications ENABLED")
        else:
            logger.info("Telegram notifications DISABLED (missing token/chat_id)")

    async def send_message(self, message: str):
        """Send a text message to the configured chat."""
        if not self.enabled:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to send Telegram message: {await resp.text()}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    async def send_alert(self, title: str, details: dict):
        """Format and send a structured alert."""
        if not self.enabled:
            return

        # Format message with emojis and HTML
        msg = f"<b>{title}</b>\n\n"
        
        for key, value in details.items():
            key_formatted = key.replace("_", " ").capitalize()
            # Truncate long values usually hashes or keys
            val_str = str(value)
            if len(val_str) > 20 and not " " in val_str: 
                val_str = f"`{val_str[:8]}...{val_str[-8:]}`"
            
            msg += f"<b>{key_formatted}:</b> {val_str}\n"

        await self.send_message(msg)
