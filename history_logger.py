# history_logger.py – Robust file‑based queue with logging and detailed status

import os
import json
import fcntl
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from pathlib import Path

from db import execute_with_retry, get_somali_time_db

logger = logging.getLogger(__name__)

# Absolute path (project root)
BASE_DIR = Path(__file__).resolve().parent
QUEUE_FILE = os.getenv('HISTORY_QUEUE_FILE') or str(BASE_DIR / 'history_queue.jsonl')
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def add_history_entry(
    user_id: int,
    entry_type: str,
    action: str,
    entry_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Append a history entry to the JSONL queue."""
    if not entry_type or not action:
        logger.warning("Skipping: missing entry_type or action")
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
        os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
        with open(QUEUE_FILE, 'a') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(entry) + '\n')
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        logger.debug(f"Queued: {entry_type} for user {user_id}")
    except Exception as e:
        logger.error(f"Write error: {e}")

    # Rotate if too large
    try:
        if os.path.exists(QUEUE_FILE) and os.path.getsize(QUEUE_FILE) > MAX_FILE_SIZE_BYTES:
            _rotate_queue_file()
    except Exception:
        pass


def flush_history_queue(limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Flush the queue file to the database.
    Returns a dict with:
        success: bool
        flushed: int (number of entries inserted)
        errors: list of error messages
        skipped: int (malformed lines)
        file_size_before: int
        file_size_after: int
    """
    result = {
        'success': False,
        'flushed': 0,
        'errors': [],
        'skipped': 0,
        'file_size_before': 0,
        'file_size_after': 0
    }

    if not os.path.exists(QUEUE_FILE):
        logger.debug("Queue file does not exist")
        result['success'] = True  # nothing to do
        return result

    result['file_size_before'] = os.path.getsize(QUEUE_FILE)

    try:
        # Read with lock
        with open(QUEUE_FILE, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            lines = f.readlines()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        if not lines:
            result['success'] = True
            result['file_size_after'] = result['file_size_before']
            return result

        logger.info(f"Flushing {len(lines)} lines from queue file ({result['file_size_before']} bytes)")

        entries = []
        malformed_lines = []

        for idx, line in enumerate(lines, 1):
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
                    malformed_lines.append(line)
                    result['skipped'] += 1
                    logger.warning(f"Line {idx} missing required fields")
            except json.JSONDecodeError as e:
                malformed_lines.append(line)
                result['skipped'] += 1
                logger.warning(f"Line {idx} invalid JSON: {e}")

        if not entries:
            logger.info("No valid entries to insert")
            # Keep malformed lines in file
            with open(QUEUE_FILE, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                if malformed_lines:
                    f.write('\n'.join(malformed_lines) + '\n')
                else:
                    f.truncate(0)
                f.flush()
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            result['success'] = True
            result['file_size_after'] = os.path.getsize(QUEUE_FILE)
            return result

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
            result['flushed'] = len(entries)
            logger.info(f"Inserted {len(entries)} entries into history_entries")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"DB insert failed: {error_msg}")
            result['errors'].append(error_msg)
            # Do NOT clear the file – we'll retry later
            result['file_size_after'] = result['file_size_before']
            return result

        # Clear the file (keep malformed lines only)
        with open(QUEUE_FILE, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            if malformed_lines:
                f.write('\n'.join(malformed_lines) + '\n')
            else:
                f.truncate(0)
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        result['success'] = True
        result['file_size_after'] = os.path.getsize(QUEUE_FILE)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Flush exception: {error_msg}")
        result['errors'].append(error_msg)

    return result


def _rotate_queue_file():
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"{QUEUE_FILE}.{timestamp}.bak"
    try:
        os.rename(QUEUE_FILE, backup_name)
        logger.info(f"Rotated queue to {backup_name}")
    except Exception as e:
        logger.error(f"Rotation failed: {e}")


def force_flush_queue() -> Dict[str, Any]:
    """Public wrapper for flush, returns the full status dict."""
    return flush_history_queue()


def recover_pending_entries() -> Dict[str, Any]:
    """Called at startup to flush any leftover entries."""
    if os.path.exists(QUEUE_FILE) and os.path.getsize(QUEUE_FILE) > 0:
        logger.info("Recovering pending history entries on startup")
        return flush_history_queue()
    return {'success': True, 'flushed': 0, 'errors': [], 'skipped': 0, 'file_size_before': 0, 'file_size_after': 0}


def get_queue_stats() -> dict:
    if os.path.exists(QUEUE_FILE):
        size = os.path.getsize(QUEUE_FILE)
        with open(QUEUE_FILE, 'r') as f:
            line_count = sum(1 for _ in f)
        return {'exists': True, 'size_bytes': size, 'line_count': line_count}
    return {'exists': False, 'size_bytes': 0, 'line_count': 0}