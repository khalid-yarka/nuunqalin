# bot/utils.py
# Shared utilities for the bot

import os
import logging
import telebot
from config import Config
from bot.db import (
    insert_pending_pdf, get_pending_pdf_by_id, get_pending_pdf_list,
    count_pending_pdfs, delete_pending_pdf, is_duplicate_pdf
)

logger = logging.getLogger(__name__)

# Global bot instance
_bot = None

def get_bot_token():
    token = Config.TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured in Config")
    return token

def get_bot() -> telebot.TeleBot:
    global _bot
    if _bot is None:
        token = get_bot_token()
        _bot = telebot.TeleBot(token, threaded=False)
    return _bot

def get_admin_ids():
    ids_str = Config.TELEGRAM_ADMIN_IDS or ''
    if ids_str:
        return [int(x.strip()) for x in ids_str.split(',') if x.strip()]
    return []

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

# Re-export DB functions for convenience
save_pending_pdf = insert_pending_pdf