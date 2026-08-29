# cache/worker.py
"""
Write-behind worker for live quiz updates.
Consumes Redis Streams and performs batched database updates.
"""

import time
import json
import logging
import threading
from typing import Dict, Any, Optional

from .manager import get_cache_manager

try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)

# Stream key
STREAM_KEY = "live_quiz_updates"
# Consumer group name
GROUP_NAME = "nuunplatform_workers"
# Consumer name (unique per worker)
CONSUMER_NAME = f"worker_{threading.get_native_id()}"

# Time to wait for new messages (milliseconds)
BLOCK_MS = 2000
# Max messages per read
COUNT = 100
# Max retries for failed updates
MAX_RETRIES = 3


def _process_entry(entry_data: Dict) -> bool:
    """
    Process a single update entry: perform the database update.
    Returns True on success, False on failure (will be retried).
    """
    quiz_id = entry_data.get('quiz_id')
    user_id = entry_data.get('user_id')
    updates = entry_data.get('updates', {})
    if not quiz_id or not user_id:
        logger.error(f"Invalid entry missing quiz_id or user_id: {entry_data}")
        return True  # skip invalid entries

    try:
        # Import db functions (lazy to avoid circular imports)
        from db import get_live_quiz_participant, update_live_quiz_participant

        participant = get_live_quiz_participant(quiz_id, user_id)
        if participant:
            # Perform update
            update_live_quiz_participant(participant['id'], updates)
            logger.debug(f"Processed update for quiz {quiz_id}, user {user_id}")
            return True
        else:
            logger.warning(f"Participant not found for quiz {quiz_id}, user {user_id}")
            return True  # No participant, nothing to update
    except Exception as e:
        logger.error(f"Error processing entry: {e}")
        return False  # Retry later


def _process_stream(redis_client: redis.Redis) -> int:
    """
    Read and process messages from the stream.
    Returns number of processed messages.
    """
    try:
        # Create consumer group if it doesn't exist
        try:
            redis_client.xgroup_create(
                STREAM_KEY, GROUP_NAME, id='0', mkstream=True
            )
        except redis.exceptions.ResponseError as e:
            # Group already exists or other error
            if 'BUSYGROUP' not in str(e):
                logger.error(f"Failed to create consumer group: {e}")

        # Read pending messages
        result = redis_client.xreadgroup(
            GROUP_NAME, CONSUMER_NAME,
            {STREAM_KEY: '>'},  # '>' means new messages
            count=COUNT,
            block=BLOCK_MS,
        )

        if not result:
            return 0

        processed = 0
        stream_messages = result[0][1]  # list of (message_id, fields)

        for message_id, fields in stream_messages:
            # fields is a dict of bytes -> bytes
            try:
                entry_data = json.loads(fields[b'data'].decode('utf-8'))
            except (KeyError, ValueError) as e:
                logger.error(f"Invalid message format: {e}")
                # Acknowledge and skip
                redis_client.xack(STREAM_KEY, GROUP_NAME, message_id)
                continue

            # Try to process with retries
            success = False
            for attempt in range(MAX_RETRIES):
                if _process_entry(entry_data):
                    success = True
                    break
                time.sleep(2 ** attempt)  # exponential backoff

            if success:
                redis_client.xack(STREAM_KEY, GROUP_NAME, message_id)
                processed += 1
            else:
                # Failed after retries; log and move on (could send to DLQ)
                logger.error(f"Failed to process entry after {MAX_RETRIES} attempts: {entry_data}")
                # Still acknowledge to avoid blocking the stream
                redis_client.xack(STREAM_KEY, GROUP_NAME, message_id)
                # Optionally publish to dead-letter queue

        return processed

    except Exception as e:
        logger.error(f"Stream processing error: {e}")
        return 0


def _worker_loop(stop_event: threading.Event):
    """Main worker loop."""
    logger.info("Cache worker started")
    redis_client = None
    try:
        from config import Config
        if Config.REDIS_URL:
            redis_client = redis.Redis.from_url(Config.REDIS_URL)
        else:
            logger.error("REDIS_URL not configured, worker cannot run.")
            return
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        return

    while not stop_event.is_set():
        try:
            processed = _process_stream(redis_client)
            if processed == 0:
                # No messages, sleep a bit to avoid busy loop
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            time.sleep(1)

    logger.info("Cache worker stopped")


# Global worker thread
_worker_thread = None
_worker_stop_event = None
_worker_started = False
_worker_lock = threading.Lock()


def start_worker():
    """Start the background worker thread."""
    global _worker_thread, _worker_stop_event, _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_stop_event = threading.Event()
        _worker_thread = threading.Thread(
            target=_worker_loop,
            args=(_worker_stop_event,),
            daemon=True,
            name="cache_worker"
        )
        _worker_thread.start()
        _worker_started = True
        logger.info("Cache worker thread started")


def stop_worker():
    """Stop the background worker thread."""
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            return
        if _worker_stop_event:
            _worker_stop_event.set()
        if _worker_thread and _worker_thread.is_alive():
            _worker_thread.join(timeout=5)
        _worker_started = False
        logger.info("Cache worker stopped")