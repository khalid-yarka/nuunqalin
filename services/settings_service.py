# services/settings_service.py
import logging
from typing import Dict, Any, Optional, Tuple
from user_settings import (
    get_raw_settings, get_user_settings, update_user_settings,
    get_migration_version, set_migration_version, MIGRATION_VERSION
)
from services.settings_registry import SETTINGS_REGISTRY, get_setting, get_default
from services.tier_service import get_current_user_tier, is_tier_at_least

logger = logging.getLogger(__name__)


class SettingsService:
    @staticmethod
    def ensure_migrated(user_id: int) -> None:
        """Run the one‑time migration if needed."""
        if get_migration_version(user_id) >= MIGRATION_VERSION:
            return

        raw = get_raw_settings(user_id)
        # Legacy key mapping (old → new)
        mapping = {
            "theme": "appearance.theme",
            "accent": "appearance.accent",
            "font_size": "appearance.font_size",
            "compact_mode": "appearance.compact_mode",
            "default_question_count": "quiz.default_question_count",
            "default_difficulty": "quiz.default_difficulty",
            "default_subject": "quiz.default_subject",
            "show_correct_immediately": "quiz.show_correct_immediately",
            "skip_rating_after_quiz": "quiz.skip_rating_after_quiz",
            "auto_skip_enabled": "quiz.auto_skip_enabled",
            "notify_quiz_complete": "notifications.quiz_complete",
            "notify_live_quiz_start": "notifications.live_quiz_start",
            "notify_live_quiz_result": "notifications.live_quiz_result",
            "notify_admin_announcement": "notifications.admin_announcement",
            "notify_participant_joined": "notifications.participant_joined",
            "notify_new_pdf": "notifications.new_pdf",
            "notify_daily_digest": "notifications.daily_digest",
            "notify_achievement_unlock": "notifications.achievement_unlock",
            "notify_live_quiz_reminder": "notifications.live_quiz_reminder",
            "notify_weekly_summary": "notifications.weekly_summary",
            "show_on_leaderboard": "privacy.show_on_leaderboard",
            "show_public_id": "privacy.show_public_id",
            "show_statistics": "privacy.show_statistics",
            "default_time_per_question": "live_quiz.default_time_per_question",
            "default_max_participants": "live_quiz.default_max_participants",
            "default_privacy": "live_quiz.default_privacy",
        }

        migrated = {}
        for old_key, new_key in mapping.items():
            # Only migrate if old key exists in raw, and new key is absent
            if old_key in raw and new_key not in raw:
                migrated[new_key] = raw[old_key]

        if migrated:
            raw.update(migrated)
            # Remove legacy keys
            for old_key in mapping.keys():
                if old_key in raw:
                    del raw[old_key]
            # Set migration version
            raw['migration_version'] = MIGRATION_VERSION
            update_user_settings(user_id, raw)
            logger.info(f"Migrated settings for user {user_id}: {migrated}")
        else:
            # If no migration needed, just set version
            raw['migration_version'] = MIGRATION_VERSION
            update_user_settings(user_id, raw)

    @staticmethod
    def get_all(user_id: int) -> Dict[str, Any]:
        """Get effective settings for the user (merged with defaults)."""
        SettingsService.ensure_migrated(user_id)
        return get_user_settings(user_id)

    @staticmethod
    def get_value(user_id: int, key: str) -> Any:
        return SettingsService.get_all(user_id).get(key)

    @staticmethod
    def validate(key: str, value: Any) -> Tuple[bool, Optional[str]]:
        definition = get_setting(key)
        if not definition:
            return False, f"Unknown setting: {key}"
        vtype = definition.get("type")
        allowed = definition.get("allowed_values")
        if vtype == "enum":
            if value not in allowed:
                return False, f"Value must be one of: {', '.join(map(str, allowed))}"
        elif vtype == "integer":
            try:
                val = int(value)
                if allowed and val not in allowed:
                    return False, f"Value must be one of: {', '.join(map(str, allowed))}"
            except (ValueError, TypeError):
                return False, "Value must be an integer"
        elif vtype == "boolean":
            if value not in (True, False, 1, 0, "true", "false", "1", "0"):
                return False, "Value must be a boolean"
            value = value in (True, 1, "true", "1")
        elif vtype == "string":
            if allowed and value not in allowed:
                return False, f"Value must be one of: {', '.join(allowed)}"
        else:
            return False, f"Unsupported type: {vtype}"
        return True, None

    @staticmethod
    def can_modify(user_id: int, key: str) -> bool:
        definition = get_setting(key)
        if not definition:
            return False
        tier_required = definition.get("tier_required")
        if not tier_required:
            return True
        user_tier = get_current_user_tier()
        return is_tier_at_least(user_tier, tier_required)

    @staticmethod
    def update(user_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Batch update settings.
        Validates, enforces tier, persists, then reads back to confirm.
        """
        normalized = {}
        for key, value in updates.items():
            valid, error = SettingsService.validate(key, value)
            if not valid:
                raise ValueError(f"Invalid value for {key}: {error}")
            if not SettingsService.can_modify(user_id, key):
                raise PermissionError(f"Setting '{key}' requires tier {get_setting(key).get('tier_required')}")
            if get_setting(key).get("type") == "boolean":
                value = value in (True, 1, "true", "1")
            normalized[key] = value

        # Write to DB
        success = update_user_settings(user_id, normalized)
        if not success:
            raise RuntimeError("Database update failed")

        # Read back to verify
        raw = get_raw_settings(user_id)
        for key, expected in normalized.items():
            actual = raw.get(key)
            if actual != expected:
                logger.error(f"Read-back mismatch for user {user_id}, key {key}: expected {expected}, got {actual}")
                raise RuntimeError(f"Persistence verification failed for key {key}")

        return SettingsService.get_all(user_id)

    @staticmethod
    def reset(user_id: int, key: str) -> Dict[str, Any]:
        definition = get_setting(key)
        if not definition:
            raise ValueError(f"Unknown setting: {key}")
        default = definition["default"]
        return SettingsService.update(user_id, {key: default})