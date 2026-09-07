# history_logger.py – Robust file-based queue with absolute path and logging

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

# Absolute path: always inside the project root (safe)
BASE_DIR = Path(__file__).resolve().parent
QUEUE_FILE = os.getenv('HISTORY_QUEUE_FILE') or str(BASE_DIR / 'history_queue.jsonl')
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


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

    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
        with open(QUEUE_FILE, 'a') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(entry) + '\n')
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        logger.debug(f"History entry written: {entry_type} for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to write history entry: {e}")

    # Rotate if too large
    try:
        if os.path.exists(QUEUE_FILE) and os.path.getsize(QUEUE_FILE) > MAX_FILE_SIZE_BYTES:
            _rotate_queue_file()
    except Exception:
        pass


# -------------------------------------------------------------------
# Flush queue
# -------------------------------------------------------------------

def flush_history_queue(limit: Optional[int] = None) -> int:
    """
    Read all entries from the queue file, bulk‑insert them into history_entries,
    then clear the file. Returns number of entries flushed.
    """
    if not os.path.exists(QUEUE_FILE):
        logger.debug("Queue file does not exist, nothing to flush")
        return 0

    entries = []
    lines_to_keep = []

    try:
        # Read with lock
        with open(QUEUE_FILE, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            lines = f.readlines()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        if not lines:
            logger.debug("Queue file is empty")
            return 0

        logger.info(f"Flushing {len(lines)} lines from history queue")

        # Parse lines
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
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
                    lines_to_keep.append(line)
                    logger.warning("Skipping malformed entry: missing fields")
            except json.JSONDecodeError:
                lines_to_keep.append(line)
                logger.warning("Skipping invalid JSON line")

        if not entries:
            logger.info("No valid entries to flush")
            return 0

        if limit and len(entries) > limit:
            entries = entries[:limit]

        # Bulk insert
        try:
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
        except Exception as e:
            logger.error(f"DB insert failed during flush: {e}")
            # Do not clear the file – we'll retry later
            return 0

        # Clear the file (keep malformed lines)
        with open(QUEUE_FILE, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            if lines_to_keep:
                f.write('\n'.join(lines_to_keep) + '\n')
            else:
                f.truncate(0)
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        logger.info(f"Successfully flushed {len(entries)} entries to DB")
        return len(entries)

    except Exception as e:
        logger.error(f"Flush failed: {e}")
        return 0


# -------------------------------------------------------------------
# Rotate file
# -------------------------------------------------------------------

def _rotate_queue_file():
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{QUEUE_FILE}.{timestamp}.bak"
        os.rename(QUEUE_FILE, backup_name)
        logger.info(f"Rotated queue to {backup_name}")
    except Exception as e:
        logger.error(f"Rotation failed: {e}")


# -------------------------------------------------------------------
# Manual flush functions
# -------------------------------------------------------------------

def force_flush_queue() -> int:
    """Public wrapper to flush all pending entries."""
    return flush_history_queue()


def recover_pending_entries() -> int:
    """Called at startup to flush any leftover entries."""
    if os.path.exists(QUEUE_FILE) and os.path.getsize(QUEUE_FILE) > 0:
        logger.info("Recovering pending history entries on startup")
        return flush_history_queue()
    return 0


# Optional: provide a way to get queue stats for debugging
def get_queue_stats() -> dict:
    if os.path.exists(QUEUE_FILE):
        size = os.path.getsize(QUEUE_FILE)
        with open(QUEUE_FILE, 'r') as f:
            line_count = sum(1 for _ in f)
        return {'exists': True, 'size_bytes': size, 'line_count': line_count}
    return {'exists': False, 'size_bytes': 0, 'line_count': 0}