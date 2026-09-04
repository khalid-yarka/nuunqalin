# bot/bot.py
# Telegram bot initialization and polling loop using telebot

import os
import logging
import threading
import telebot
from telebot import types

from bot.handlers import handle_document, handle_start, handle_help, handle_admin_pending
from bot.utils import is_admin

logger = logging.getLogger(__name__)

# Global bot instance
_bot = None
_polling_thread = None

def get_bot_token():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    return token

def get_bot() -> telebot.TeleBot:
    global _bot
    if _bot is None:
        token = get_bot_token()
        _bot = telebot.TeleBot(token, threaded=False)
        _register_handlers()
    return _bot

def _register_handlers():
    """Register all message and callback handlers."""
    bot = _bot
    if bot is None:
        return

    @bot.message_handler(commands=['start'])
    def start_handler(message):
        handle_start(bot, message)

    @bot.message_handler(commands=['help'])
    def help_handler(message):
        handle_help(bot, message)

    @bot.message_handler(content_types=['document'])
    def document_handler(message):
        handle_document(bot, message)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('pdf_admin_'))
    def callback_handler(call):
        handle_admin_pending(bot, call)

def start_bot():
    """Start the Telegram bot in a separate thread."""
    global _polling_thread
    if _polling_thread and _polling_thread.is_alive():
        logger.info("Bot already running")
        return

    bot = get_bot()

    def run_polling():
        logger.info("Starting Telegram bot polling (telebot)...")
        try:
            bot.polling(non_stop=True, interval=1, timeout=30)
        except Exception as e:
            logger.error(f"Bot polling error: {e}")
        finally:
            logger.info("Telegram bot polling stopped")

    _polling_thread = threading.Thread(target=run_polling, daemon=True)
    _polling_thread.start()
    logger.info("Telegram bot thread started")

def stop_bot():
    """Stop the bot (not fully supported by telebot, but we can try)."""
    global _bot, _polling_thread
    if _bot:
        try:
            _bot.stop_polling()
        except Exception:
            pass
        _bot = None
    if _polling_thread:
        _polling_thread.join(timeout=2)
        _polling_thread = None
    logger.info("Telegram bot stopped")