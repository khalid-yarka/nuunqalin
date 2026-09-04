# bot/utils.py
# Shared utilities for the bot

import os
import logging
import telebot
from db import execute_with_retry

logger = logging.getLogger(__name__)

# Global bot instance
_bot = None

def get_bot_token():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    return token

def get_bot() -> telebot.TeleBot:
    """Get or create the global TeleBot instance."""
    global _bot
    if _bot is None:
        token = get_bot_token()
        _bot = telebot.TeleBot(token, threaded=False)
    return _bot

def get_admin_ids():
    ids_str = os.getenv('TELEGRAM_ADMIN_IDS', '')
    if ids_str:
        return [int(x.strip()) for x in ids_str.split(',') if x.strip()]
    return []

def is_admin(user_id: int) -> bool:
    """Check if a Telegram user is an admin."""
    return user_id in get_admin_ids()

# Database helpers
def is_duplicate_pdf(file_unique_id: str) -> bool:
    """Check if a PDF with this file_unique_id already exists in pending_pdfs or pdfs."""
    cursor = execute_with_retry(
        "SELECT id FROM pending_pdfs WHERE file_unique_id = ?",
        (file_unique_id,)
    )
    if cursor.fetchone():
        return True
    cursor = execute_with_retry(
        "SELECT id FROM pdfs WHERE file_unique_id = ?",
        (file_unique_id,)
    )
    if cursor.fetchone():
        return True
    return False

def save_pending_pdf(file_id: str, file_unique_id: str, filename: str, uploaded_by: int) -> int:
    """Insert a new pending PDF record and return its ID."""
    try:
        cursor = execute_with_retry(
            """
            INSERT INTO pending_pdfs (file_id, file_unique_id, filename, uploaded_by)
            VALUES (?, ?, ?, ?)
            """,
            (file_id, file_unique_id, filename, uploaded_by),
            commit=True
        )
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to save pending PDF: {e}")
        return 0

def get_pending_pdfs_count() -> int:
    cursor = execute_with_retry("SELECT COUNT(*) as count FROM pending_pdfs")
    row = cursor.fetchone()
    return row['count'] if row else 0

def get_pending_pdf_list(limit=50, offset=0):
    cursor = execute_with_retry(
        """
        SELECT id, file_id, file_unique_id, filename, uploaded_by, uploaded_at
        FROM pending_pdfs
        ORDER BY uploaded_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset)
    )
    rows = cursor.fetchall()
    return [dict(row) for row in rows]

def get_pending_pdf_by_id(pending_id: int):
    cursor = execute_with_retry(
        "SELECT * FROM pending_pdfs WHERE id = ?",
        (pending_id,)
    )
    row = cursor.fetchone()
    return dict(row) if row else None

def delete_pending_pdf(pending_id: int) -> bool:
    try:
        execute_with_retry(
            "DELETE FROM pending_pdfs WHERE id = ?",
            (pending_id,),
            commit=True
        )
        return True
    except Exception:
        return False