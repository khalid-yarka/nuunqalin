# history_logger.py – Asynchronous history entry logger

import json
import queue
import threading
import time
import logging
from typing import Dict, Any, Optional

from db import execute_with_retry, get_somali_time_db

logger = logging.getLogger(__name__)

_history_queue = queue.Queue()
_worker_running = False
_worker_thread = None
BATCH_SIZE = 50
FLUSH_INTERVAL = 2  # seconds


def add_history_entry(
    user_id: int,
    entry_type: str,
    action: str,
    entry_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Enqueue a history entry to be written asynchronously.
    """
    entry = {
        'user_id': user_id,
        'entry_type': entry_type,
        'action': action,
        'entry_id': entry_id,
        'metadata': json.dumps(metadata or {}),
        'created_at': get_somali_time_db()
    }
    _history_queue.put(entry)
    _ensure_worker()


def _ensure_worker():
    global _worker_running, _worker_thread
    if not _worker_running:
        _worker_running = True
        _worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        _worker_thread.start()
        logger.info("History logger worker started.")


def _worker_loop():
    batch = []
    last_flush = time.time()
    while True:
        try:
            item = _history_queue.get(timeout=1)
            batch.append(item)
        except queue.Empty:
            pass
        now = time.time()
        if len(batch) >= BATCH_SIZE or (batch and (now - last_flush) >= FLUSH_INTERVAL):
            _flush_batch(batch)
            batch = []
            last_flush = now


def _flush_batch(batch):
    if not batch:
        return
    try:
        sql = """
            INSERT INTO history_entries
            (user_id, entry_type, action, entry_id, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = [
            (e['user_id'], e['entry_type'], e['action'],
             e['entry_id'], e['metadata'], e['created_at'])
            for e in batch
        ]
        execute_with_retry(sql, params, commit=True, operation_name='history_batch_insert')
    except Exception as e:
        logger.error(f"Failed to flush history batch: {e}")