# bot/db.py
# Separate database connection and operations for the bot (pending_pdfs only)

import os
import sqlite3
import logging
from config import Config

logger = logging.getLogger(__name__)

BOT_DB_PATH = Config.BOT_DATABASE_PATH

def _get_connection():
    """Get a direct connection to the bot database."""
    db_dir = os.path.dirname(BOT_DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(BOT_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def init_bot_db():
    """Create the pending_pdfs table if it doesn't exist."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_pdfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL,
            file_unique_id TEXT UNIQUE NOT NULL,
            filename TEXT,
            uploaded_by INTEGER,
            uploaded_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_pdfs_uploaded_at ON pending_pdfs(uploaded_at DESC)")
    conn.commit()
    conn.close()
    logger.info("Bot database initialized (pending_pdfs table ready).")

def execute_query(query, params=(), commit=False):
    """Execute a query and return cursor and connection."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    if commit:
        conn.commit()
    return cursor, conn

def insert_pending_pdf(file_id, file_unique_id, filename, uploaded_by):
    """Insert a new pending PDF record and return its ID."""
    try:
        cursor, conn = execute_query(
            """
            INSERT INTO pending_pdfs (file_id, file_unique_id, filename, uploaded_by)
            VALUES (?, ?, ?, ?)
            """,
            (file_id, file_unique_id, filename, uploaded_by),
            commit=True
        )
        conn.close()
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to save pending PDF: {e}")
        return 0

def get_pending_pdf_by_id(pending_id):
    cursor, conn = execute_query(
        "SELECT * FROM pending_pdfs WHERE id = ?",
        (pending_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_pending_pdf_list(limit=50, offset=0):
    cursor, conn = execute_query("""
        SELECT * FROM pending_pdfs
        ORDER BY uploaded_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def count_pending_pdfs():
    cursor, conn = execute_query("SELECT COUNT(*) as count FROM pending_pdfs")
    row = cursor.fetchone()
    conn.close()
    return row['count'] if row else 0

def delete_pending_pdf(pending_id):
    try:
        execute_query(
            "DELETE FROM pending_pdfs WHERE id = ?",
            (pending_id,),
            commit=True
        )
        return True
    except Exception:
        return False

def is_duplicate_pdf(file_unique_id):
    """Check if a PDF with this file_unique_id exists in pending_pdfs."""
    cursor, conn = execute_query(
        "SELECT id FROM pending_pdfs WHERE file_unique_id = ?",
        (file_unique_id,)
    )
    result = cursor.fetchone() is not None
    conn.close()
    return result

def drop_pending_table():
    """Drop the pending_pdfs table (used for reset)."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS pending_pdfs")
    conn.commit()
    conn.close()
    logger.info("pending_pdfs table dropped")