# bot/bot.py
# Telegram bot initialization and polling loop using telebot

import logging
import threading
import telebot
from telebot import types

from bot.handlers import handle_document, handle_start, handle_help, handle_admin_pending
from bot.utils import get_bot, is_admin, get_bot_token

logger = logging.getLogger(__name__)

# Global references
_bot = None
_polling_thread = None

def _register_handlers(bot: telebot.TeleBot):
    """Register all message and callback handlers."""
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

    try:
        bot = get_bot()
        _register_handlers(bot)

        # Remove any existing webhook to avoid 404 errors
        try:
            bot.remove_webhook()
            logger.info("Removed existing webhook")
        except Exception as e:
            logger.warning(f"Failed to remove webhook: {e}")

        # Test the bot by getting me info
        try:
            me = bot.get_me()
            logger.info(f"Bot connected: @{me.username} (ID: {me.id})")
        except Exception as e:
            logger.error(f"Bot get_me failed: {e} - check your token")
            return

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
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)

def stop_bot():
    """Stop the bot."""
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