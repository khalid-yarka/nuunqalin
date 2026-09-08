# services/settings_service.py
"""
Centralized Settings Service.
"""
import logging
from typing import Dict, Any, Optional, Tuple
from db import execute_with_retry
from user_settings import get_user_settings, update_user_settings
from services.settings_registry import SETTINGS_REGISTRY, get_setting, get_default
from services.tier_service import get_current_user_tier, is_tier_at_least

logger = logging.getLogger(__name__)

class SettingsService:
    @staticmethod
    def get_all(user_id: int) -> Dict[str, Any]:
        stored = get_user_settings(user_id) or {}
        defaults = {k: v["default"] for k, v in SETTINGS_REGISTRY.items()}
        merged = defaults.copy()
        merged.update(stored)
        # Remove stale keys
        cleaned = {k: v for k, v in merged.items() if k in SETTINGS_REGISTRY}
        return cleaned

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
    def set_value(user_id: int, key: str, value: Any) -> Dict[str, Any]:
        valid, error = SettingsService.validate(key, value)
        if not valid:
            raise ValueError(error)
        if not SettingsService.can_modify(user_id, key):
            raise PermissionError(f"Setting '{key}' requires tier {get_setting(key).get('tier_required')}")
        if get_setting(key).get("type") == "boolean":
            value = value in (True, 1, "true", "1")
        current = get_user_settings(user_id) or {}
        current[key] = value
        update_user_settings(user_id, current)
        return SettingsService.get_all(user_id)

    @staticmethod
    def update(user_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in updates.items():
            valid, error = SettingsService.validate(key, value)
            if not valid:
                raise ValueError(f"Invalid value for {key}: {error}")
            if not SettingsService.can_modify(user_id, key):
                raise PermissionError(f"Setting '{key}' requires tier {get_setting(key).get('tier_required')}")
            if get_setting(key).get("type") == "boolean":
                value = value in (True, 1, "true", "1")
            updates[key] = value
        current = get_user_settings(user_id) or {}
        current.update(updates)
        update_user_settings(user_id, current)
        return SettingsService.get_all(user_id)

    @staticmethod
    def reset(user_id: int, key: str) -> Dict[str, Any]:
        definition = get_setting(key)
        if not definition:
            raise ValueError(f"Unknown setting: {key}")
        default = definition["default"]
        return SettingsService.set_value(user_id, key, default)

    @staticmethod
    def reset_all(user_id: int) -> Dict[str, Any]:
        defaults = {k: v["default"] for k, v in SETTINGS_REGISTRY.items()}
        update_user_settings(user_id, defaults)
        return defaults

    @staticmethod
    def migrate_old_settings(user_id: int) -> None:
        stored = get_user_settings(user_id) or {}
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
            if old_key in stored:
                migrated[new_key] = stored[old_key]
        if migrated:
            current = get_user_settings(user_id) or {}
            current.update(migrated)
            update_user_settings(user_id, current)
            logger.info(f"Migrated old settings for user {user_id}: {migrated}")