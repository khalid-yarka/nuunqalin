# user_settings.py
import json
from typing import Any, Dict, Optional
from db import execute_with_retry

DEFAULT_SETTINGS = {
    "theme": "system",
    "default_question_count": 10,
    "default_difficulty": 0,
    "show_correct_immediately": 1,
    "skip_rating_after_quiz": 0,
    "show_on_leaderboard": 1,
    "show_public_id": 1,
    "notify_quiz_complete": 1,
    "notify_live_quiz_start": 1,
    "notify_live_quiz_result": 1,
    "notify_admin_announcement": 1,
    "notify_participant_joined": 1,
    "notify_new_pdf": 1,
}

MIGRATION_VERSION = 1  # current version


def get_raw_settings(user_id: int) -> Dict[str, Any]:
    """Get the raw settings JSON from the database without merging defaults."""
    cursor = execute_with_retry(
        "SELECT settings FROM user_settings WHERE user_id = ?", (user_id,)
    )
    row = cursor.fetchone()
    if row and row['settings']:
        try:
            return json.loads(row['settings'])
        except json.JSONDecodeError:
            return {}
    return {}


def get_migration_version(user_id: int) -> int:
    raw = get_raw_settings(user_id)
    return raw.get('migration_version', 0)


def set_migration_version(user_id: int, version: int) -> None:
    raw = get_raw_settings(user_id)
    raw['migration_version'] = version
    update_user_settings(user_id, raw)


def get_user_settings(user_id: int) -> Dict[str, Any]:
    """
    Retrieve effective settings: defaults + stored settings.
    """
    stored = get_raw_settings(user_id)
    merged = DEFAULT_SETTINGS.copy()
    # Merge stored, but skip migration_version (internal)
    stored_without_version = {k: v for k, v in stored.items() if k != 'migration_version'}
    merged.update(stored_without_version)
    return merged


def update_user_settings(user_id: int, updates: Dict[str, Any]) -> bool:
    """
    Update the stored settings with the given dict.
    This does NOT merge defaults; it writes exactly the provided keys.
    The migration_version field is preserved if not explicitly overwritten.
    """
    try:
        raw = get_raw_settings(user_id)
        # If migration_version exists, keep it; else set to 0 (will be upgraded later)
        if 'migration_version' not in raw:
            raw['migration_version'] = 0
        # Apply updates
        for key, value in updates.items():
            if key == 'migration_version':
                continue  # handled above
            raw[key] = value
        execute_with_retry(
            """
            INSERT INTO user_settings (user_id, settings, updated_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            ON CONFLICT(user_id) DO UPDATE SET
                settings = excluded.settings,
                updated_at = excluded.updated_at
            """,
            (user_id, json.dumps(raw)),
            commit=True
        )
        return True
    except Exception:
        return False


def apply_user_theme(user_id: int) -> str:
    """Get the user's theme preference, or 'system' as fallback."""
    return get_user_settings(user_id).get('theme', 'system')