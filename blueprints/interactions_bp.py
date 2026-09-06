# blueprints/interactions_bp.py
# API endpoints for quiz interactions

from flask import Blueprint, request, session, jsonify
from functools import wraps
from services.interaction_service import (
    toggle_like, toggle_save, submit_report, get_user_interaction_status, get_question_likes
)
from db import get_question_by_id
from utils import validate_csrf

interactions_bp = Blueprint('interactions', __name__, url_prefix='/api/interaction')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Please login first.'}), 401
        return f(*args, **kwargs)
    return decorated

@interactions_bp.route('/like', methods=['POST'])
@login_required
def like():
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403

    data = request.get_json()
    question_id = data.get('question_id')
    if not question_id:
        return jsonify({'error': 'Missing question_id'}), 400

    q = get_question_by_id(question_id)
    if not q:
        return jsonify({'error': 'Question not found'}), 404

    result = toggle_like(session['user_id'], int(question_id))
    return jsonify(result)

@interactions_bp.route('/save', methods=['POST'])
@login_required
def save():
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403

    data = request.get_json()
    question_id = data.get('question_id')
    if not question_id:
        return jsonify({'error': 'Missing question_id'}), 400

    q = get_question_by_id(question_id)
    if not q:
        return jsonify({'error': 'Question not found'}), 404

    result = toggle_save(session['user_id'], int(question_id))
    return jsonify(result)

@interactions_bp.route('/report', methods=['POST'])
@login_required
def report():
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403

    data = request.get_json()
    question_id = data.get('question_id')
    reason = data.get('reason')
    comment = data.get('comment', '').strip()

    if not question_id or not reason:
        return jsonify({'error': 'Missing question_id or reason'}), 400

    q = get_question_by_id(question_id)
    if not q:
        return jsonify({'error': 'Question not found'}), 404

    result = submit_report(session['user_id'], int(question_id), reason, comment)
    return jsonify(result)

@interactions_bp.route('/status', methods=['GET'])
@login_required
def status():
    question_id = request.args.get('question_id')
    if not question_id:
        return jsonify({'error': 'Missing question_id'}), 400

    status_data = get_user_interaction_status(session['user_id'], int(question_id))
    status_data['like_count'] = get_question_likes(int(question_id))
    return jsonify(status_data)