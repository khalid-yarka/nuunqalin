# services/achievement_service.py
# Minimal achievement system.

import logging
from typing import List, Dict, Optional
from db import execute_with_retry, get_student_by_id
from tier_service import get_achievement_history_level, get_badge_showcase_level

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Achievements Definition (pre‑populated)
# -------------------------------------------------------------------

ACHIEVEMENTS = [
    {
        "name": "First Quiz",
        "description": "Complete your first quiz.",
        "icon": "🏁",
        "tier_required": "danbe",
        "unlock_condition": "complete_quiz_count >= 1",
    },
    {
        "name": "Quiz Master",
        "description": "Complete 10 quizzes.",
        "icon": "🎓",
        "tier_required": "danbe",
        "unlock_condition": "complete_quiz_count >= 10",
    },
    {
        "name": "Perfect Score",
        "description": "Get 100% on a quiz.",
        "icon": "💯",
        "tier_required": "danbe",
        "unlock_condition": "perfect_quiz",
    },
    {
        "name": "Live Participant",
        "description": "Join your first live quiz.",
        "icon": "⚡",
        "tier_required": "danbe",
        "unlock_condition": "live_quiz_joined",
    },
    {
        "name": "Achievement Hunter",
        "description": "Earn 5 achievements.",
        "icon": "🏆",
        "tier_required": "dhexe",
        "unlock_condition": "achievement_count >= 5",
    },
    {
        "name": "Premium Learner",
        "description": "Access premium resources.",
        "icon": "💎",
        "tier_required": "dhexe",
        "unlock_condition": "premium_resource_access",
    },
]

def get_achievement_definitions():
    return ACHIEVEMENTS

# -------------------------------------------------------------------
# Database Helpers
# -------------------------------------------------------------------

def ensure_achievements_seeded():
    """Insert predefined achievements if they don't exist."""
    try:
        for ach in ACHIEVEMENTS:
            cursor = execute_with_retry(
                "SELECT id FROM achievements WHERE name = ?",
                (ach["name"],)
            )
            if not cursor.fetchone():
                execute_with_retry("""
                    INSERT INTO achievements (name, description, icon, tier_required, unlock_condition)
                    VALUES (?, ?, ?, ?, ?)
                """, (ach["name"], ach["description"], ach["icon"], ach["tier_required"], ach["unlock_condition"]),
                commit=True)
        logger.info("Achievements seeded successfully.")
    except Exception as e:
        logger.error(f"Failed to seed achievements: {e}")

def get_all_achievements() -> List[Dict]:
    cursor = execute_with_retry("SELECT * FROM achievements ORDER BY id")
    rows = cursor.fetchall()
    return [dict(row) for row in rows]

def get_user_achievement_ids(user_id: int) -> List[int]:
    cursor = execute_with_retry(
        "SELECT achievement_id FROM user_achievements WHERE user_id = ?",
        (user_id,)
    )
    return [row['achievement_id'] for row in cursor.fetchall()]

def award_achievement(user_id: int, achievement_id: int) -> bool:
    """Award an achievement if not already earned."""
    cursor = execute_with_retry(
        "SELECT id FROM user_achievements WHERE user_id = ? AND achievement_id = ?",
        (user_id, achievement_id)
    )
    if cursor.fetchone():
        return False
    execute_with_retry(
        "INSERT INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
        (user_id, achievement_id), commit=True
    )
    return True

def get_user_achievements(user_id: int) -> List[Dict]:
    cursor = execute_with_retry("""
        SELECT a.*, ua.unlocked_at
        FROM user_achievements ua
        JOIN achievements a ON ua.achievement_id = a.id
        WHERE ua.user_id = ?
        ORDER BY ua.unlocked_at DESC
    """, (user_id,))
    return [dict(row) for row in cursor.fetchall()]

# -------------------------------------------------------------------
# Condition Evaluation
# -------------------------------------------------------------------

def evaluate_conditions(user_id: int, event: str, data: Dict) -> List[int]:
    """
    Given an event (e.g., 'quiz_completed') and associated data,
    return a list of achievement IDs that should be awarded.
    """
    # Get user stats
    from db import execute_with_retry
    # Count quizzes completed
    cursor = execute_with_retry(
        "SELECT COUNT(*) as cnt FROM quiz_attempts WHERE student_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    quiz_count = row['cnt'] if row else 0

    # Check for perfect quiz
    perfect = False
    if event == 'quiz_completed':
        score = data.get('score', 0)
        total = data.get('total', 0)
        if total > 0 and score == total:
            perfect = True

    # Live quiz joined
    live_joined = False
    if event == 'live_quiz_joined':
        live_joined = True

    # Achievement count
    achievements = get_user_achievement_ids(user_id)
    ach_count = len(achievements)

    # Premium resource access (we can track via a flag in user_settings or just by checking if user has ever accessed one)
    premium_access = False
    # We can check if user has any premium resource download in resource_downloads? 
    # For simplicity, we'll check if user has a flag in user_settings.
    # But we'll skip that for now.

    # Now check all achievements
    to_award = []
    all_ach = get_all_achievements()
    for ach in all_ach:
        if ach['id'] in achievements:
            continue
        condition = ach['unlock_condition']
        # Evaluate simple conditions
        if condition == 'complete_quiz_count >= 1' and quiz_count >= 1:
            to_award.append(ach['id'])
        elif condition == 'complete_quiz_count >= 10' and quiz_count >= 10:
            to_award.append(ach['id'])
        elif condition == 'perfect_quiz' and perfect:
            to_award.append(ach['id'])
        elif condition == 'live_quiz_joined' and live_joined:
            to_award.append(ach['id'])
        elif condition == 'achievement_count >= 5' and ach_count >= 5:
            to_award.append(ach['id'])
        elif condition == 'premium_resource_access' and premium_access:
            to_award.append(ach['id'])
    return to_award

def check_and_award_achievements(user_id: int, event: str, data: Dict):
    """Evaluate conditions and award any new achievements."""
    to_award = evaluate_conditions(user_id, event, data)
    awarded = []
    for ach_id in to_award:
        if award_achievement(user_id, ach_id):
            awarded.append(ach_id)
    return awarded

# -------------------------------------------------------------------
# Tier‑aware Display Helpers
# -------------------------------------------------------------------

def get_visible_achievements(user_id: int) -> List[Dict]:
    """Return achievements visible to the user based on tier level."""
    level = get_achievement_history_level(user_id)
    all_user_ach = get_user_achievements(user_id)
    if level == 1:
        # limited/recent: last 10
        return all_user_ach[:10]
    elif level == 2:
        # expanded: last 50
        return all_user_ach[:50]
    else:
        # complete: all
        return all_user_ach

def get_showcase_badges(user_id: int) -> List[Dict]:
    """Return badges for showcase, limited by tier."""
    level = get_badge_showcase_level(user_id)
    all_ach = get_user_achievements(user_id)
    # For showcase, we might want to return only a few, e.g., top 3.
    # We'll just return the first N based on level.
    if level == 1:
        return all_ach[:3]
    elif level == 2:
        return all_ach[:6]
    else:
        return all_ach  # all