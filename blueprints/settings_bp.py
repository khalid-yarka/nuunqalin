# blueprints/settings_bp.py
from flask import Blueprint, render_template, request, session, jsonify
from functools import wraps
from services.settings_service import SettingsService
from services.settings_registry import get_all_categories
from services.tier_service import get_current_user_tier, can_create_live_quiz
from utils import validate_csrf

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Please login first.'}), 401
        return f(*args, **kwargs)
    return decorated

@settings_bp.route('/')
@login_required
def index():
    user_id = session['user_id']
    SettingsService.migrate_old_settings(user_id)
    tier = get_current_user_tier()
    settings = SettingsService.get_all(user_id)
    categories = get_all_categories()
    can_create = can_create_live_quiz()
    return render_template('settings/index.html',
                           tier=tier,
                           settings=settings,
                           categories=categories,
                           can_create_live=can_create)

@settings_bp.route('/api', methods=['GET'])
@login_required
def api_get():
    user_id = session['user_id']
    category = request.args.get('category')
    settings = SettingsService.get_all(user_id)
    if category:
        category_keys = {k for k, v in SETTINGS_REGISTRY.items() if v.get('category') == category}
        settings = {k: v for k, v in settings.items() if k in category_keys}
    return jsonify(settings)

@settings_bp.route('/api', methods=['PATCH'])
@login_required
def api_patch():
    if not validate_csrf():
        return jsonify({'error': 'CSRF validation failed'}), 403
    user_id = session['user_id']
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    try:
        updated = SettingsService.update(user_id, data)
        return jsonify({'success': True, 'settings': updated})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        return jsonify({'error': 'Internal server error'}), 500

@settings_bp.route('/api/reset', methods=['POST'])
@login_required
def api_reset():
    if not validate_csrf():
        return jsonify({'error': 'CSRF validation failed'}), 403
    user_id = session['user_id']
    data = request.get_json()
    key = data.get('key')
    if not key:
        return jsonify({'error': 'Missing key'}), 400
    try:
        updated = SettingsService.reset(user_id, key)
        return jsonify({'success': True, 'settings': updated})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        return jsonify({'error': 'Internal server error'}), 500

# Password change endpoint (kept separate for security)
@settings_bp.route('/api/password', methods=['POST'])
@login_required
def api_password():
    if not validate_csrf():
        return jsonify({'error': 'CSRF validation failed'}), 403
    user_id = session['user_id']
    data = request.get_json()
    current = data.get('current_password', '')
    new = data.get('new_password', '')
    confirm = data.get('confirm_password', '')
    if not current or not new or not confirm:
        return jsonify({'error': 'All fields are required.'}), 400
    if new != confirm:
        return jsonify({'error': 'Passwords do not match.'}), 400
    if len(new) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400
    from db import get_student_by_id, execute_with_retry
    student = get_student_by_id(user_id)
    if not student or student['password'] != current:
        return jsonify({'error': 'Current password is incorrect.'}), 400
    execute_with_retry(
        "UPDATE students SET password = ? WHERE id = ?",
        (new, user_id),
        commit=True
    )
    return jsonify({'success': True, 'message': 'Password changed. Please log in again.'})