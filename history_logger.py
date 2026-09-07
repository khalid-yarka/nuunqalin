# history_logger.py
# Asynchronous history logger using a persistent file-based queue (JSONL).
# Works on PythonAnywhere Free – no threads, no Redis.

import os
import json
import fcntl
import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

from db import execute_with_retry, get_somali_time_db

logger = logging.getLogger(__name__)

# Configuration – you can override these via environment variables
QUEUE_FILE = os.getenv('HISTORY_QUEUE_FILE', 'history_queue.jsonl')
MAX_BATCH_SIZE = 100          # Maximum entries to flush in one go
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB – rotate if exceeded


# -------------------------------------------------------------------
# Write to queue (append one JSON line)
# -------------------------------------------------------------------

def add_history_entry(
    user_id: int,
    entry_type: str,
    action: str,
    entry_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Append a history entry to the local JSONL queue file.
    This is called synchronously inside the request – it's very fast
    and does not touch the main database.
    """
    if not entry_type or not action:
        logger.warning("Skipping history entry: missing entry_type or action")
        return

    entry = {
        'user_id': user_id,
        'entry_type': entry_type,
        'action': action,
        'entry_id': entry_id,
        'metadata': json.dumps(metadata or {}),
        'created_at': get_somali_time_db()
    }

    # Write atomically with lock
    try:
        with open(QUEUE_FILE, 'a') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(entry) + '\n')
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.error(f"Failed to write history entry to queue: {e}")

    # Rotate file if it grows too large (avoid disk full)
    try:
        if os.path.exists(QUEUE_FILE) and os.path.getsize(QUEUE_FILE) > MAX_FILE_SIZE_BYTES:
            _rotate_queue_file()
    except Exception:
        pass


# -------------------------------------------------------------------
# Flush queue: read all lines, insert into DB, then truncate
# -------------------------------------------------------------------

def flush_history_queue(limit: Optional[int] = None) -> int:
    """
    Read all entries from the queue file, bulk‑insert them into
    the history_entries table, and then clear the file.
    Returns number of entries flushed.
    """
    if not os.path.exists(QUEUE_FILE):
        return 0

    entries = []
    lines_to_keep = []  # in case of partial failure

    try:
        # Read the file with lock
        with open(QUEUE_FILE, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            lines = f.readlines()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        if not lines:
            return 0

        # Parse JSON lines
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                # Ensure we have all required fields
                if all(k in entry for k in ('user_id', 'entry_type', 'action', 'metadata', 'created_at')):
                    entries.append((
                        entry['user_id'],
                        entry['entry_type'],
                        entry['action'],
                        entry.get('entry_id'),
                        entry['metadata'],
                        entry['created_at']
                    ))
                else:
                    # Keep malformed lines for manual inspection
                    lines_to_keep.append(line)
                    logger.warning(f"Skipping malformed history entry: missing fields")
            except json.JSONDecodeError as e:
                lines_to_keep.append(line)
                logger.warning(f"Invalid JSON in history queue: {e}")

        if not entries:
            return 0

        # Apply optional limit (for cron or manual flush)
        if limit and len(entries) > limit:
            entries = entries[:limit]

        # Bulk insert
        if entries:
            execute_with_retry(
                """
                INSERT INTO history_entries
                (user_id, entry_type, action, entry_id, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                entries,
                commit=True,
                operation_name='history_flush'
            )

        # After successful insert, clear the file (keep only malformed lines)
        with open(QUEUE_FILE, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            if lines_to_keep:
                f.write('\n'.join(lines_to_keep) + '\n')
            else:
                f.truncate(0)
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        logger.info(f"Flushed {len(entries)} history entries to DB")
        return len(entries)

    except Exception as e:
        logger.error(f"Error flushing history queue: {e}")
        # Do not delete the file; it will be retried next time
        return 0


# -------------------------------------------------------------------
# Rotate queue file (rename and create empty)
# -------------------------------------------------------------------

def _rotate_queue_file():
    """Rename the queue file to a timestamped backup and create a new empty one."""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{QUEUE_FILE}.{timestamp}.bak"
        os.rename(QUEUE_FILE, backup_name)
        logger.info(f"Rotated history queue to {backup_name}")
    except Exception as e:
        logger.error(f"Failed to rotate history queue: {e}")


# -------------------------------------------------------------------
# Force flush (for cron or manual invocation)
# -------------------------------------------------------------------

def force_flush_queue() -> int:
    """Public function to flush the entire queue (used by cron or endpoint)."""
    return flush_history_queue()


# -------------------------------------------------------------------
# Recover pending entries on application startup
# -------------------------------------------------------------------

def recover_pending_entries() -> int:
    """
    Called during app startup to flush any leftover entries from the queue.
    Returns number of entries flushed.
    """
    if os.path.exists(QUEUE_FILE):
        size = os.path.getsize(QUEUE_FILE)
        if size > 0:
            logger.info(f"Found pending history entries ({size} bytes). Flushing...")
            return flush_history_queue()
    return 0