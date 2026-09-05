# bot/bot.py
# Telegram bot initialization using webhook (no polling)

import os
import logging
import requests
import telebot
from telebot import types

from bot.handlers import process_telegram_update
from bot.utils import get_bot_token
from config import Config

logger = logging.getLogger(__name__)

# Global bot instance
_bot = None

def get_bot():
    global _bot
    if _bot is None:
        token = get_bot_token()
        _bot = telebot.TeleBot(token, threaded=False)
        logger.info("TeleBot instance created.")
    return _bot

def set_webhook():
    """Register the webhook URL with Telegram."""
    bot = get_bot()
    token = get_bot_token()
    base_url = Config.BASE_URL
    if not base_url:
        logger.error("BASE_URL not configured in Config! Cannot set webhook.")
        return False
    webhook_path = f"/webhook/{token}"
    webhook_url = f"{base_url}{webhook_path}"

    try:
        url = f"https://api.telegram.org/bot{token}/setWebhook"
        payload = {
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": True
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200 and response.json().get('ok'):
            logger.info(f"Webhook set successfully: {webhook_url}")
            return True
        else:
            logger.error(f"Failed to set webhook: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return False

def delete_webhook():
    """Delete the webhook."""
    token = get_bot_token()
    try:
        url = f"https://api.telegram.org/bot{token}/deleteWebhook"
        response = requests.get(url, timeout=10)
        if response.status_code == 200 and response.json().get('ok'):
            logger.info("Webhook deleted successfully.")
        else:
            logger.warning(f"Failed to delete webhook: {response.text}")
    except Exception as e:
        logger.warning(f"Error deleting webhook: {e}")

def start_bot():
    """Set up the webhook (no polling)."""
    set_webhook()
    logger.info("Bot configured to use webhook.")

def stop_bot():
    """Clean up webhook (optional)."""
    delete_webhook()
    logger.info("Bot webhook removed.")