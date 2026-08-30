# user_settings.py
import json
from typing import Any, Dict, Optional
from db import execute_with_retry

# Default settings (applied when user has no saved settings)
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


def get_user_settings(user_id: int) -> Dict[str, Any]:
    """
    Retrieve the full settings dict for a user, merged with defaults.
    """
    cursor = execute_with_retry(
        "SELECT settings FROM user_settings WHERE user_id = ?", (user_id,)
    )
    row = cursor.fetchone()
    if row and row['settings']:
        try:
            saved = json.loads(row['settings'])
            # Merge with defaults (so missing keys get default values)
            merged = DEFAULT_SETTINGS.copy()
            merged.update(saved)
            return merged
        except json.JSONDecodeError:
            pass
    return DEFAULT_SETTINGS.copy()


def get_user_setting(user_id: int, key: str, default: Any = None) -> Any:
    """Get a single user setting."""
    settings = get_user_settings(user_id)
    return settings.get(key, default)


def update_user_settings(user_id: int, updates: Dict[str, Any]) -> bool:
    """
    Merge updates into user's settings and save.
    Returns True on success.
    """
    current = get_user_settings(user_id)
    current.update(updates)

    # Validate / sanitize (optional, but good practice)
    # For now, just ensure booleans are ints (SQLite stores as int)
    for k, v in current.items():
        if isinstance(v, bool):
            current[k] = 1 if v else 0

    try:
        execute_with_retry("""
            INSERT INTO user_settings (user_id, settings, updated_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            ON CONFLICT(user_id) DO UPDATE SET
                settings = excluded.settings,
                updated_at = excluded.updated_at
        """, (user_id, json.dumps(current)), commit=True)
        return True
    except Exception:
        return False


def apply_user_theme(user_id: int) -> str:
    """Get the user's theme preference, or 'system' as fallback."""
    return get_user_setting(user_id, 'theme', 'system')