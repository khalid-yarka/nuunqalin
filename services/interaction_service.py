# services/interaction_service.py
# Quiz interaction service: likes, saves, reports

import json
import logging
from typing import Optional, Dict, Any, List
from db import execute_with_retry, get_db, get_question_by_id
from services.tier_service import get_saved_content_limit, get_saved_content_count
from utils import get_somali_time_db
from live_quiz_state import get_live_quiz_state_manager

logger = logging.getLogger(__name__)

# ============================================
# Save counting
# ============================================

def count_user_saves(user_id: int) -> int:
    """Count total saved questions for a user (across regular and live quizzes)."""
    cursor = execute_with_retry(
        "SELECT COUNT(*) as count FROM question_interactions WHERE user_id = ? AND interaction_type = 'save'",
        (user_id,)
    )
    row = cursor.fetchone()
    return row['count'] if row else 0

def get_user_saves(user_id: int, limit: int = 50, offset: int = 0) -> List[Dict]:
    """Get saved questions for a user."""
    cursor = execute_with_retry("""
        SELECT q.*, qi.created_at as saved_at
        FROM question_interactions qi
        JOIN questions q ON qi.question_id = q.id
        WHERE qi.user_id = ? AND qi.interaction_type = 'save'
        ORDER BY qi.created_at DESC
        LIMIT ? OFFSET ?
    """, (user_id, limit, offset))
    rows = cursor.fetchall()
    return [dict(row) for row in rows]

# ============================================
# Like
# ============================================

def toggle_like(user_id: int, question_id: int, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Toggle like on a question.
    context: optional, for live quizzes: {'live_quiz_id': int, 'participant_state': ...}
    For regular quizzes, writes directly to DB.
    For live quizzes, uses in-memory state.
    """
    # Check if user is in a live quiz
    manager = get_live_quiz_state_manager()
    active_quiz_id = None
    quiz_state = None

    # Try to find an active live quiz for this user
    for qid in manager.get_all_active_quizzes():
        qs = manager.get_quiz(qid)
        if qs and qs.is_active() and qs.get_participant(user_id):
            active_quiz_id = qid
            quiz_state = qs
            break

    if quiz_state:
        # Live quiz – use in-memory
        result = quiz_state.toggle_like(user_id, question_id)
        if not result:
            return {'error': 'Could not toggle like'}
        # Get updated like count for the question (from all participants)
        like_count = sum(1 for p in quiz_state.participants.values() if question_id in p.likes)
        return {'liked': question_id in quiz_state.get_participant(user_id).likes, 'count': like_count}

    # Regular quiz – direct DB write
    cursor = execute_with_retry(
        "SELECT id FROM question_interactions WHERE user_id = ? AND question_id = ? AND interaction_type = 'like'",
        (user_id, question_id)
    )
    existing = cursor.fetchone()

    if existing:
        execute_with_retry(
            "DELETE FROM question_interactions WHERE id = ?",
            (existing['id'],),
            commit=True
        )
        liked = False
    else:
        # Check if there is a quiz_attempt_id for this user/question (regular quiz)
        # We can try to find the latest attempt for this question
        cursor = execute_with_retry(
            """SELECT id FROM quiz_attempts
               WHERE student_id = ? AND completed_at IS NOT NULL
               ORDER BY completed_at DESC LIMIT 1""",
            (user_id,)
        )
        attempt_row = cursor.fetchone()
        attempt_id = attempt_row['id'] if attempt_row else None

        execute_with_retry(
            """INSERT INTO question_interactions 
               (user_id, question_id, quiz_attempt_id, interaction_type)
               VALUES (?, ?, ?, 'like')""",
            (user_id, question_id, attempt_id),
            commit=True
        )
        liked = True

    # Get updated like count
    cursor = execute_with_retry(
        "SELECT COUNT(*) as count FROM question_interactions WHERE question_id = ? AND interaction_type = 'like'",
        (question_id,)
    )
    row = cursor.fetchone()
    count = row['count'] if row else 0

    return {'liked': liked, 'count': count}

# ============================================
# Save / Bookmark
# ============================================

def toggle_save(user_id: int, question_id: int) -> Dict[str, Any]:
    """Toggle save on a question. Works for both regular and live quizzes."""
    # Check tier limit
    limit = get_saved_content_limit(user_id)
    if limit is not None:
        save_count = count_user_saves(user_id)
        if save_count >= limit:
            return {'saved': False, 'error': 'Save limit reached', 'limit': limit}

    # Check if user is in a live quiz
    manager = get_live_quiz_state_manager()
    quiz_state = None
    for qid in manager.get_all_active_quizzes():
        qs = manager.get_quiz(qid)
        if qs and qs.is_active() and qs.get_participant(user_id):
            quiz_state = qs
            break

    if quiz_state:
        # Live quiz – in-memory
        result = quiz_state.toggle_save(user_id, question_id)
        if not result:
            return {'error': 'Could not toggle save'}
        # Get updated counts
        p = quiz_state.get_participant(user_id)
        saved = question_id in p.saves if p else False
        total_saves = count_user_saves(user_id)  # count from all quizzes (in case of mixed)
        return {'saved': saved, 'total_saves': total_saves}

    # Regular quiz – direct DB
    cursor = execute_with_retry(
        "SELECT id FROM question_interactions WHERE user_id = ? AND question_id = ? AND interaction_type = 'save'",
        (user_id, question_id)
    )
    existing = cursor.fetchone()

    if existing:
        execute_with_retry(
            "DELETE FROM question_interactions WHERE id = ?",
            (existing['id'],),
            commit=True
        )
        saved = False
    else:
        cursor = execute_with_retry(
            """SELECT id FROM quiz_attempts
               WHERE student_id = ? AND completed_at IS NOT NULL
               ORDER BY completed_at DESC LIMIT 1""",
            (user_id,)
        )
        attempt_row = cursor.fetchone()
        attempt_id = attempt_row['id'] if attempt_row else None

        execute_with_retry(
            """INSERT INTO question_interactions
               (user_id, question_id, quiz_attempt_id, interaction_type)
               VALUES (?, ?, ?, 'save')""",
            (user_id, question_id, attempt_id),
            commit=True
        )
        saved = True

    total_saves = count_user_saves(user_id)
    return {'saved': saved, 'total_saves': total_saves}

# ============================================
# Report
# ============================================

REPORT_REASONS = [
    {'id': 'incorrect', 'label': 'Incorrect Answer'},
    {'id': 'inappropriate', 'label': 'Inappropriate Content'},
    {'id': 'spam', 'label': 'Spam or Irrelevant'},
    {'id': 'duplicate', 'label': 'Duplicate Question'},
    {'id': 'other', 'label': 'Other'},
]

def submit_report(user_id: int, question_id: int, reason: str, comment: str = '') -> Dict[str, Any]:
    """Submit a report. Works for both regular and live quizzes."""
    # Check if already reported this question
    cursor = execute_with_retry(
        """SELECT id FROM question_interactions
           WHERE user_id = ? AND question_id = ? AND interaction_type = 'report'""",
        (user_id, question_id)
    )
    if cursor.fetchone():
        return {'success': False, 'error': 'You have already reported this question.'}

    # Determine if this is part of a live quiz
    manager = get_live_quiz_state_manager()
    live_quiz_id = None
    for qid in manager.get_all_active_quizzes():
        qs = manager.get_quiz(qid)
        if qs and qs.is_active() and qs.get_participant(user_id):
            live_quiz_id = qid
            break

    # Insert directly into DB
    execute_with_retry(
        """INSERT INTO question_interactions
           (user_id, question_id, live_quiz_id, interaction_type, report_reason, report_comment, report_status)
           VALUES (?, ?, ?, 'report', ?, ?, 'pending')""",
        (user_id, question_id, live_quiz_id, reason, comment),
        commit=True
    )

    # Notify admins
    from db import create_notification_for_all_users
    question = get_question_by_id(question_id)
    question_text = question['question_text'][:50] + '...' if question else 'Unknown question'
    create_notification_for_all_users(
        type='admin_report',
        title='⚠️ New Report',
        body=f'User #{user_id} reported: "{question_text}"',
        link=f'/admin/reports',
        icon='⚠️'
    )

    return {'success': True, 'message': 'Report submitted. We will review it shortly.'}

# ============================================
# Admin report management
# ============================================

def get_pending_reports(limit: int = 50, offset: int = 0) -> List[Dict]:
    cursor = execute_with_retry("""
        SELECT qi.*, q.question_text, s.first_name, s.last_name, s.public_id
        FROM question_interactions qi
        JOIN questions q ON qi.question_id = q.id
        JOIN students s ON qi.user_id = s.id
        WHERE qi.interaction_type = 'report' AND qi.report_status = 'pending'
        ORDER BY qi.created_at ASC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    rows = cursor.fetchall()
    return [dict(row) for row in rows]

def get_all_reports(limit: int = 50, offset: int = 0, status: str = None) -> List[Dict]:
    query = """
        SELECT qi.*, q.question_text, s.first_name, s.last_name, s.public_id,
               adm.first_name as admin_first_name, adm.last_name as admin_last_name
        FROM question_interactions qi
        JOIN questions q ON qi.question_id = q.id
        JOIN students s ON qi.user_id = s.id
        LEFT JOIN students adm ON qi.resolved_by = adm.id
        WHERE qi.interaction_type = 'report'
    """
    params = []
    if status:
        query += " AND qi.report_status = ?"
        params.append(status)
    query += " ORDER BY qi.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = execute_with_retry(query, params)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]

def count_reports(status: str = None) -> int:
    query = "SELECT COUNT(*) as count FROM question_interactions WHERE interaction_type = 'report'"
    params = []
    if status:
        query += " AND report_status = ?"
        params.append(status)
    cursor = execute_with_retry(query, params)
    row = cursor.fetchone()
    return row['count'] if row else 0

def resolve_report(report_id: int, admin_id: int, reply: str = '') -> bool:
    try:
        if reply:
            execute_with_retry(
                """UPDATE question_interactions
                   SET report_status = 'resolved', resolved_by = ?, resolved_at = ?, admin_reply = ?
                   WHERE id = ? AND interaction_type = 'report'""",
                (admin_id, get_somali_time_db(), reply, report_id),
                commit=True
            )
        else:
            execute_with_retry(
                """UPDATE question_interactions
                   SET report_status = 'resolved', resolved_by = ?, resolved_at = ?
                   WHERE id = ? AND interaction_type = 'report'""",
                (admin_id, get_somali_time_db(), report_id),
                commit=True
            )
        return True
    except Exception as e:
        logger.error(f"Error resolving report: {e}")
        return False

def dismiss_report(report_id: int, admin_id: int, reply: str = '') -> bool:
    try:
        if reply:
            execute_with_retry(
                """UPDATE question_interactions
                   SET report_status = 'dismissed', resolved_by = ?, resolved_at = ?, admin_reply = ?
                   WHERE id = ? AND interaction_type = 'report'""",
                (admin_id, get_somali_time_db(), reply, report_id),
                commit=True
            )
        else:
            execute_with_retry(
                """UPDATE question_interactions
                   SET report_status = 'dismissed', resolved_by = ?, resolved_at = ?
                   WHERE id = ? AND interaction_type = 'report'""",
                (admin_id, get_somali_time_db(), report_id),
                commit=True
            )
        return True
    except Exception as e:
        logger.error(f"Error dismissing report: {e}")
        return False

def get_report_by_id(report_id: int) -> Optional[Dict]:
    cursor = execute_with_retry("""
        SELECT qi.*, q.question_text, s.first_name, s.last_name, s.public_id
        FROM question_interactions qi
        JOIN questions q ON qi.question_id = q.id
        JOIN students s ON qi.user_id = s.id
        WHERE qi.id = ? AND qi.interaction_type = 'report'
    """, (report_id,))
    row = cursor.fetchone()
    return dict(row) if row else None

# ============================================
# Get user interaction status for a question
# ============================================

def get_user_interaction_status(user_id: int, question_id: int) -> Dict[str, Any]:
    cursor = execute_with_retry(
        "SELECT interaction_type FROM question_interactions WHERE user_id = ? AND question_id = ?",
        (user_id, question_id)
    )
    rows = cursor.fetchall()
    actions = [row['interaction_type'] for row in rows]
    return {
        'liked': 'like' in actions,
        'saved': 'save' in actions,
        'reported': 'report' in actions,
    }

def get_question_likes(question_id: int) -> int:
    cursor = execute_with_retry(
        "SELECT COUNT(*) as count FROM question_interactions WHERE question_id = ? AND interaction_type = 'like'",
        (question_id,)
    )
    row = cursor.fetchone()
    return row['count'] if row else 0