# blueprints/user_settings_bp.py
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from functools import wraps
from db import get_student_by_id, is_admin, execute_with_retry
from user_settings import get_user_settings, update_user_settings, get_user_setting
from services.tier_service import get_feature_level, get_current_user_tier
from activity_logger import log_activity

user_settings_bp = Blueprint('user_settings', __name__, url_prefix='/settings')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@user_settings_bp.route('/')
@login_required
def index():
    """User settings page."""
    user_id = session['user_id']
    student = get_student_by_id(user_id)
    settings = get_user_settings(user_id)
    
    # Tier levels
    tier = get_current_user_tier()
    profile_level = get_feature_level("profile_customization", user_id)
    notif_level = get_feature_level("notification_settings", user_id)
    
    return render_template('dashboard/user_settings.html',
                           student=student,
                           settings=settings,
                           tier=tier,
                           profile_level=profile_level,
                           notif_level=notif_level)

@user_settings_bp.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    """Update profile fields."""
    user_id = session['user_id']
    data = request.get_json() or {}
    updates = {}
    for field in ['first_name', 'last_name', 'middle_name', 'school', 'grade', 'city', 'location']:
        if field in data:
            updates[field] = data[field].strip()
    # Basic validation
    if 'first_name' in updates and (len(updates['first_name']) < 4 or not updates['first_name'].isalpha()):
        return jsonify({'error': 'First name must be at least 4 letters and contain only letters.'}), 400
    if 'last_name' in updates and (len(updates['last_name']) < 4 or not updates['last_name'].isalpha()):
        return jsonify({'error': 'Last name must be at least 4 letters and contain only letters.'}), 400

    # Update student table
    for field, value in updates.items():
        execute_with_retry(
            f"UPDATE students SET {field} = ? WHERE id = ?",
            (value, user_id),
            commit=True
        )
    log_activity('user.profile_update', f"User {user_id} updated profile", 'info', user_id=user_id)
    return jsonify({'success': True, 'message': 'Profile updated!'})

@user_settings_bp.route('/update-appearance', methods=['POST'])
@login_required
def update_appearance():
    """Update theme/language."""
    user_id = session['user_id']
    data = request.get_json() or {}
    theme = data.get('theme')
    if theme not in ['light', 'dark', 'system']:
        return jsonify({'error': 'Invalid theme.'}), 400
    update_user_settings(user_id, {'theme': theme})
    log_activity('user.theme_update', f"User {user_id} changed theme to {theme}", 'info', user_id=user_id)
    return jsonify({'success': True, 'message': 'Theme updated!'})

@user_settings_bp.route('/update-quiz-preferences', methods=['POST'])
@login_required
def update_quiz_preferences():
    user_id = session['user_id']
    data = request.get_json() or {}
    # Validate
    try:
        q_count = int(data.get('default_question_count', 10))
        if q_count not in [5, 10, 15, 20, 25, 30]:
            return jsonify({'error': 'Invalid question count.'}), 400
    except ValueError:
        return jsonify({'error': 'Invalid question count.'}), 400

    diff = int(data.get('default_difficulty', 0))
    if diff not in range(0, 6):
        return jsonify({'error': 'Invalid difficulty.'}), 400

    show_correct = 1 if data.get('show_correct_immediately') in [True, 'true', 1] else 0
    skip_rating = 1 if data.get('skip_rating_after_quiz') in [True, 'true', 1] else 0

    updates = {
        'default_question_count': q_count,
        'default_difficulty': diff,
        'show_correct_immediately': show_correct,
        'skip_rating_after_quiz': skip_rating
    }
    update_user_settings(user_id, updates)
    log_activity('user.quiz_preferences_update', f"User {user_id} updated quiz preferences", 'info', user_id=user_id)
    return jsonify({'success': True, 'message': 'Quiz preferences saved!'})

@user_settings_bp.route('/update-notifications', methods=['POST'])
@login_required
def update_notifications():
    user_id = session['user_id']
    data = request.get_json() or {}
    
    # Base notification keys (always available)
    base_keys = [
        'notify_quiz_complete',
        'notify_live_quiz_start',
        'notify_live_quiz_result',
        'notify_admin_announcement',
        'notify_participant_joined',
        'notify_new_pdf'
    ]
    
    # Expanded keys (for level 2 and above)
    expanded_keys = [
        'notify_weekly_summary',
        'notify_achievement_unlock'
    ]
    
    # Advanced keys (for level 3)
    advanced_keys = [
        'notify_custom_digest',
        'notify_friend_activity'
    ]
    
    notif_level = get_feature_level("notification_settings", user_id)
    
    allowed_keys = base_keys.copy()
    if notif_level >= 2:
        allowed_keys.extend(expanded_keys)
    if notif_level >= 3:
        allowed_keys.extend(advanced_keys)
    
    updates = {}
    for key in allowed_keys:
        if key in data:
            updates[key] = 1 if data[key] in [True, 'true', 1] else 0
    
    if updates:
        update_user_settings(user_id, updates)
        log_activity('user.notification_preferences_update', f"User {user_id} updated notification preferences", 'info', user_id=user_id)
    return jsonify({'success': True, 'message': 'Notification preferences saved!'})

@user_settings_bp.route('/update-privacy', methods=['POST'])
@login_required
def update_privacy():
    user_id = session['user_id']
    data = request.get_json() or {}
    updates = {}
    for key in ['show_on_leaderboard', 'show_public_id']:
        if key in data:
            updates[key] = 1 if data[key] in [True, 'true', 1] else 0
    if updates:
        update_user_settings(user_id, updates)
        log_activity('user.privacy_update', f"User {user_id} updated privacy settings", 'info', user_id=user_id)
    return jsonify({'success': True, 'message': 'Privacy settings saved!'})

@user_settings_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    user_id = session['user_id']
    data = request.get_json() or {}
    current = data.get('current_password', '')
    new = data.get('new_password', '')
    confirm = data.get('confirm_password', '')

    if not current or not new or not confirm:
        return jsonify({'error': 'All fields are required.'}), 400
    if new != confirm:
        return jsonify({'error': 'New passwords do not match.'}), 400
    if len(new) < 8:
        return jsonify({'error': 'New password must be at least 8 characters.'}), 400

    # Verify current password (plaintext for now – improve later)
    student = get_student_by_id(user_id)
    if not student or student['password'] != current:
        return jsonify({'error': 'Current password is incorrect.'}), 400

    # Update password
    execute_with_retry(
        "UPDATE students SET password = ? WHERE id = ?",
        (new, user_id),
        commit=True
    )
    log_activity('user.password_change', f"User {user_id} changed password", 'warning', user_id=user_id)
    return jsonify({'success': True, 'message': 'Password changed. Please log in again.'})