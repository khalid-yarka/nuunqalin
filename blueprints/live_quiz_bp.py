# blueprints/live_quiz_bp.py
"""
Live Quiz Blueprint - Complete with Scheduling & Notifications
Updated to use subject_code instead of subject_id, and validate against user's allowed subjects.
"""

from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify, Response
from functools import wraps
from datetime import datetime, timezone, timedelta
import secrets
import string
import json
import time
import csv
from io import StringIO
import threading
import logging
import random

from db import (
    get_questions_by_subject,
    get_question_by_id,
    get_live_quiz_by_id,
    get_live_quiz_by_code,
    get_live_quiz_with_subject,
    get_live_quiz_participant,
    get_live_quiz_participants,
    get_live_quiz_participants_with_names,
    get_live_quiz_count,
    get_live_quiz_completed_count,
    get_question_ids_for_quiz,
    get_questions_by_ids,
    get_live_quiz_creator_id,
    get_active_live_quiz,
    get_student_by_id,
    get_live_quizzes_lobby,
    get_live_quiz_stats,
    can_join_live_quiz,
    leave_live_quiz as db_leave_live_quiz,
    rejoin_live_quiz as db_rejoin_live_quiz,
    get_active_participants,
    delete_live_quiz as db_delete_live_quiz,
    get_user_active_quiz,
    is_admin,
    create_live_quiz,
    update_live_quiz,
    add_live_quiz_participant,
    update_live_quiz_participant,
    update_participant_ready,
    create_notification,
    get_user_subject_list,
    notify_live_quiz_start,
    notify_live_quiz_results,
    notify_participant_joined,
)

from config import Config
from utils import get_somali_time_db, get_somali_time_display, format_somali_time, validate_csrf, ensure_csrf_token
from subjects_config import get_subject, get_all_subjects

from cache import get_cache_manager, InvalidationHelper, make_key
from cache.worker import STREAM_KEY as CACHE_STREAM_KEY

try:
    import redis
    _redis_client = None
    def get_redis_client():
        global _redis_client
        if _redis_client is None and Config.REDIS_URL:
            try:
                _redis_client = redis.Redis.from_url(Config.REDIS_URL)
            except Exception:
                _redis_client = None
        return _redis_client
except ImportError:
    _redis_client = None
    def get_redis_client():
        return None

live_quiz_bp = Blueprint('live_quiz', __name__, url_prefix='/live-quiz')

MAX_PARTICIPANTS = Config.LIVE_QUIZ_MAX_PARTICIPANTS
TIME_PER_QUESTION = Config.LIVE_QUIZ_TIME_PER_QUESTION
RATING_TIME = Config.RATING_TIME
CACHE_TTL = getattr(Config, 'CACHE_TTL', {}).get('quiz', {})
QUIZ_STATE_TTL = CACHE_TTL.get('state', 60)
PARTICIPANTS_TTL = CACHE_TTL.get('participants', 30)
LEADERBOARD_TTL = CACHE_TTL.get('leaderboard', 10)

def get_cache():
    return get_cache_manager()

def get_quiz_cache_key(quiz_id: int, suffix: str = 'state') -> str:
    return make_key('quiz', suffix, str(quiz_id))

def get_participants_cache_key(quiz_id: int) -> str:
    return get_quiz_cache_key(quiz_id, 'participants')

def get_leaderboard_cache_key(quiz_id: int) -> str:
    return get_quiz_cache_key(quiz_id, 'leaderboard')

def get_quiz_from_cache(quiz_id: int):
    cache = get_cache()
    key = get_quiz_cache_key(quiz_id)
    def load_from_db():
        return get_live_quiz_with_subject(quiz_id)
    return cache.get_or_compute(key=key, compute_func=load_from_db, ttl=QUIZ_STATE_TTL)

def get_participants_from_cache(quiz_id: int):
    cache = get_cache()
    key = get_participants_cache_key(quiz_id)
    def load_from_db():
        return get_live_quiz_participants_with_names(quiz_id)
    return cache.get_or_compute(key=key, compute_func=load_from_db, ttl=PARTICIPANTS_TTL)

def get_leaderboard_from_cache(quiz_id: int, limit: int = 10):
    cache = get_cache()
    key = get_leaderboard_cache_key(quiz_id)
    def load_from_db():
        participants = get_live_quiz_participants_with_names(quiz_id)
        active = [p for p in participants if p.get('status') != 'left']
        sorted_p = sorted(active, key=lambda x: x.get('score', 0), reverse=True)
        result = []
        for i, p in enumerate(sorted_p[:limit], 1):
            student = p.get('student', {})
            result.append({
                'user_id': p.get('student_id'),
                'student_id': p.get('student_id'),
                'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant',
                'score': p.get('score', 0),
                'rank': i,
                'correct': p.get('correct_count', 0),
                'wrong': p.get('wrong_count', 0),
                'current_question_index': p.get('current_question_index', 0)
            })
        return result
    return cache.get_or_compute(key=key, compute_func=load_from_db, ttl=LEADERBOARD_TTL)

def invalidate_quiz_cache(quiz_id: int):
    InvalidationHelper.invalidate_quiz(quiz_id)
    cache = get_cache()
    cache.invalidate_pattern(f"quiz:*:{quiz_id}:*")

def update_participant_async(quiz_id: int, user_id: int, updates: dict):
    cache = get_cache()
    cache_key = get_participants_cache_key(quiz_id)
    participants = cache.get(cache_key)
    if participants:
        updated = False
        for p in participants:
            if p.get('student_id') == user_id or p.get('user_id') == user_id:
                p.update(updates)
                updated = True
                break
        if updated:
            cache.set(cache_key, participants, ttl=PARTICIPANTS_TTL)
    individual_key = make_key('quiz', 'participant', f"{quiz_id}:{user_id}")
    individual = cache.get(individual_key)
    if individual:
        individual.update(updates)
        cache.set(individual_key, individual, ttl=PARTICIPANTS_TTL)
    cache.delete(get_leaderboard_cache_key(quiz_id))
    redis_client = get_redis_client()
    if redis_client:
        try:
            redis_client.xadd(CACHE_STREAM_KEY, {'data': json.dumps({'quiz_id': quiz_id, 'user_id': user_id, 'updates': updates, 'timestamp': time.time()})})
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to push update to queue: {e}")
    else:
        try:
            participant = get_live_quiz_participant(quiz_id, user_id)
            if participant:
                update_live_quiz_participant(participant['id'], updates)
        except Exception as e:
            logging.getLogger(__name__).error(f"Direct DB update failed: {e}")

def get_participant_safe(quiz_id: int, user_id: int):
    cache = get_cache()
    individual_key = make_key('quiz', 'participant', f"{quiz_id}:{user_id}")
    participant = cache.get(individual_key)
    if participant:
        return participant
    participant = get_live_quiz_participant(quiz_id, user_id)
    if participant:
        student = get_student_by_id(user_id)
        name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant' if student else 'Participant'
        participant['name'] = name
        cache.set(individual_key, participant, ttl=PARTICIPANTS_TTL)
        participants_key = get_participants_cache_key(quiz_id)
        participants = cache.get(participants_key)
        if participants:
            found = False
            for p in participants:
                if p.get('student_id') == user_id:
                    p.update(participant)
                    found = True
                    break
            if not found:
                participants.append(participant)
            cache.set(participants_key, participants, ttl=PARTICIPANTS_TTL)
    return participant

def add_participant_to_cache(quiz_id: int, user_id: int, participant_data: dict):
    cache = get_cache()
    participants_key = get_participants_cache_key(quiz_id)
    participants = cache.get(participants_key) or []
    for p in participants:
        if p.get('student_id') == user_id:
            return
    participants.append(participant_data)
    cache.set(participants_key, participants, ttl=PARTICIPANTS_TTL)
    individual_key = make_key('quiz', 'participant', f"{quiz_id}:{user_id}")
    cache.set(individual_key, participant_data, ttl=PARTICIPANTS_TTL)
    cache.delete(get_leaderboard_cache_key(quiz_id))

# ============================================
# HELPER FUNCTIONS
# ============================================

def generate_join_code():
    letters = ''.join(secrets.choice(string.ascii_uppercase + '123456789') for _ in range(4))
    numbers = ''.join(secrets.choice('123456789') for _ in range(4))
    return f"{letters}-{numbers}"

def generate_unique_join_code():
    code = generate_join_code()
    while True:
        quiz = get_live_quiz_by_code(code)
        if not quiz:
            return code
        code = generate_join_code()

def get_questions_for_subject(subject_code, limit):
    questions = get_questions_by_subject(subject_code, limit)
    return questions, len(questions)

def get_quiz_or_redirect(quiz_id, user_id, required_status=None, check_participant=False, allow_creator=False):
    quiz = get_quiz_from_cache(quiz_id)
    if not quiz:
        flash('Quiz not found or has been deleted.', 'error')
        return None, None, redirect(url_for('live_quiz.lobby'))
    if required_status:
        if isinstance(required_status, str):
            allowed = [required_status]
        else:
            allowed = required_status
        current_status = quiz.get('status')
        if current_status not in allowed:
            if current_status == 'waiting':
                flash('This quiz has not started yet. Go to the waiting room.', 'info')
                return None, None, redirect(url_for('live_quiz.waiting_room', quiz_id=quiz_id))
            elif current_status == 'finished':
                flash('This quiz has already finished. Viewing results.', 'info')
                return None, None, redirect(url_for('live_quiz.results', quiz_id=quiz_id))
            else:
                flash('Quiz is not available in its current state.', 'error')
                return None, None, redirect(url_for('live_quiz.lobby'))
    participant = None
    if check_participant:
        participant = get_participant_safe(quiz_id, user_id)
        if not participant:
            if allow_creator and quiz.get('creator_id') == user_id:
                pass
            else:
                flash('You are not a participant in this quiz.', 'error')
                return None, None, redirect(url_for('live_quiz.lobby'))
        elif participant.get('status') == 'left':
            if current_status in ['waiting', 'scheduled']:
                flash('You left this quiz. You can rejoin from the waiting room.', 'info')
                return None, None, redirect(url_for('live_quiz.waiting_room', quiz_id=quiz_id))
            else:
                flash('You left this quiz and cannot rejoin.', 'error')
                return None, None, redirect(url_for('live_quiz.lobby'))
    return quiz, participant, None

def finalize_live_quiz(quiz_id: int) -> dict:
    try:
        quiz = get_live_quiz_by_id(quiz_id)
        if not quiz:
            return {'success': False, 'message': 'Quiz not found'}
        if quiz.get('status') == 'finished':
            return {'success': True, 'message': 'Already finished'}
        update_live_quiz(quiz_id, {'status': 'finished', 'ended_at': get_somali_time_db()})
        participants = get_live_quiz_participants_with_names(quiz_id)
        if not participants:
            invalidate_quiz_cache(quiz_id)
            return {'success': True, 'message': 'Quiz finished (no participants)'}
        sorted_parts = sorted(participants, key=lambda x: x.get('score', 0), reverse=True)
        for i, p in enumerate(sorted_parts, 1):
            update_live_quiz_participant(p['id'], {'ranking': i})
        invalidate_quiz_cache(quiz_id)
        notify_live_quiz_results(quiz_id, quiz.get('title', 'Live Quiz'), sorted_parts)
        return {'success': True, 'message': 'Quiz finalized', 'participants': sorted_parts}
    except Exception as e:
        logging.getLogger(__name__).error(f"Error finalizing quiz {quiz_id}: {e}")
        return {'success': False, 'message': str(e)}

def start_cache_cleanup():
    def cleanup_loop():
        while True:
            try:
                cache = get_cache()
                time.sleep(300)
            except Exception as e:
                logging.getLogger(__name__).error(f"Cache cleanup error: {e}")
                time.sleep(60)
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    return thread

_cleanup_thread = start_cache_cleanup()

# ============================================
# TEMPLATE FILTER FOR SOMALI TIME
# ============================================

@live_quiz_bp.app_template_filter('format_somali_time')
def format_somali_time_filter(dt_str):
    """Convert ISO datetime string to Somali time format."""
    if not dt_str:
        return ''
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return format_somali_time(dt)
    except Exception:
        return dt_str

# ============================================
# ROUTES
# ============================================

@live_quiz_bp.route('/')
def index():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    return redirect(url_for('live_quiz.lobby'))

@live_quiz_bp.route('/lobby')
def lobby():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    status_filter = request.args.get('status', '')
    subject_filter = request.args.get('subject', '')
    search = request.args.get('search', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 20
    subject_code = None
    if subject_filter:
        all_subjects = get_all_subjects()
        if any(s['code'] == subject_filter for s in all_subjects):
            subject_code = subject_filter
        else:
            subject_code = None

    cache = get_cache()
    subjects_key = make_key('subject', 'list', 'all')
    subjects = cache.get(subjects_key)
    if subjects is None:
        subjects = get_all_subjects()
        cache.set(subjects_key, subjects, ttl=3600)

    quizzes, total = get_live_quizzes_lobby(
        user_id=session['user_id'],
        status_filter=status_filter if status_filter else None,
        subject_filter=subject_code,
        search=search if search else None,
        page=page,
        per_page=per_page
    )

    stats_key = make_key('quiz', 'stats', 'global')
    stats = cache.get(stats_key)
    if stats is None:
        stats = get_live_quiz_stats()
        cache.set(stats_key, stats, ttl=30)

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    return render_template('dashboard/live_quiz/lobby.html',
                         quizzes=quizzes, stats=stats, subjects=subjects,
                         status_filter=status_filter, subject_filter=subject_filter,
                         search=search, page=page, per_page=per_page,
                         total=total, total_pages=total_pages)

@live_quiz_bp.route('/lobby/join/<quiz_id>', methods=['POST'])
def lobby_join(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Please login first'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    quiz, _, redirect_resp = get_quiz_or_redirect(quiz_id, user_id, required_status=['waiting', 'scheduled'], check_participant=False)
    if redirect_resp:
        location = redirect_resp.headers.get('Location', url_for('live_quiz.lobby'))
        if location and '/waiting-room/' in location:
            return jsonify({'success': True, 'redirect': location, 'message': 'Quiz is scheduled or waiting'})
        return jsonify({'error': 'Quiz not available', 'redirect': location}), 400
    participant = get_participant_safe(quiz_id, user_id)
    if participant:
        if participant.get('status') == 'left':
            if quiz['status'] in ['waiting', 'scheduled']:
                success = db_rejoin_live_quiz(quiz_id, user_id)
                if success:
                    participant['status'] = 'active'
                    participant['score'] = 0
                    participant['current_question_index'] = 0
                    add_participant_to_cache(quiz_id, user_id, participant)
                    return jsonify({'success': True, 'redirect': url_for('live_quiz.waiting_room', quiz_id=quiz_id), 'rejoined': True})
                else:
                    return jsonify({'error': 'Failed to rejoin'}), 500
            else:
                return jsonify({'error': 'Cannot rejoin an active quiz'}), 400
        else:
            return jsonify({'success': True, 'redirect': url_for('live_quiz.waiting_room', quiz_id=quiz_id), 'already_joined': True})
    can_join, reason = can_join_live_quiz(quiz_id, user_id)
    if not can_join:
        return jsonify({'error': reason}), 400
    participant_count = get_live_quiz_count(quiz_id)
    if participant_count >= quiz.get('max_participants', 50):
        return jsonify({'error': 'Quiz is full'}), 400
    active_quiz = get_user_active_quiz(user_id)
    if active_quiz and active_quiz != int(quiz_id):
        return jsonify({'error': 'You are already in another quiz. Please leave that quiz first.'}), 400
    add_live_quiz_participant(quiz_id, user_id)
    user = get_student_by_id(user_id)
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant'
    participant_data = {
        'student_id': user_id,
        'user_id': user_id,
        'name': user_name,
        'score': 0,
        'current_question_index': 0,
        'correct_count': 0,
        'wrong_count': 0,
        'skipped_count': 0,
        'answers': {},
        'ratings': {},
        'status': 'active',
        'joined_at': get_somali_time_db()
    }
    add_participant_to_cache(quiz_id, user_id, participant_data)
    notify_participant_joined(quiz_id, quiz.get('title', 'Live Quiz'), user_name, quiz['creator_id'])
    return jsonify({'success': True, 'redirect': url_for('live_quiz.waiting_room', quiz_id=quiz_id)})

# ============================================
# CREATE LIVE QUIZ - GET & POST
# ============================================

@live_quiz_bp.route('/create', methods=['GET', 'POST'])
def create():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']

    user_subjects = get_user_subject_list(user_id)

    # Ensure CSRF token exists for GET requests
    if request.method == 'GET':
        ensure_csrf_token()

    if request.method == 'POST':
        # CSRF validation
        if not validate_csrf():
            flash('Invalid CSRF token. Please try again.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)

        subject_code = request.form.get('subject_code', '').strip()
        allowed_codes = [s['code'] for s in user_subjects]
        if subject_code not in allowed_codes:
            flash('Subject not available for your location/curriculum.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)

        question_count = int(request.form.get('question_count', 10))
        title = request.form.get('title', '').strip()
        is_public = int(request.form.get('is_public', 1))
        schedule_minutes = int(request.form.get('schedule_minutes', 0))

        if not title:
            flash('Please enter a title for your quiz.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects,
                                   subject_code=subject_code, title=title, is_public=is_public)

        if not subject_code:
            flash('Please select a subject.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)

        questions, available = get_questions_for_subject(subject_code, question_count)

        if available == 0:
            flash('No questions available for this subject. Please select another subject.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)

        if available < question_count:
            return render_template('dashboard/live_quiz/create.html',
                                   subjects=user_subjects, not_enough=True,
                                   available=available, requested=question_count,
                                   subject_code=subject_code, title=title, is_public=is_public)

        join_code = generate_unique_join_code()
        question_ids = [q['id'] for q in questions]

        data = {
            'creator_id': user_id,
            'title': title if title else '',
            'subject_code': subject_code,
            'question_count': question_count,
            'join_code': join_code,
            'max_participants': MAX_PARTICIPANTS,
            'time_per_question': TIME_PER_QUESTION,
            'current_question_index': 0,
            'question_ids': question_ids,
            'is_public': is_public
        }

        if schedule_minutes > 0:
            data['status'] = 'scheduled'
            scheduled_time = datetime.now(timezone.utc) + timedelta(minutes=schedule_minutes)
            data['scheduled_start'] = scheduled_time.isoformat()
        else:
            data['status'] = 'waiting'
            data['scheduled_start'] = None

        quiz = create_live_quiz(data)

        if quiz:
            add_live_quiz_participant(quiz['id'], user_id)
            cache = get_cache()
            cache.set(get_quiz_cache_key(quiz['id']), quiz, ttl=QUIZ_STATE_TTL)
            user = get_student_by_id(user_id)
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant'
            participant_data = {
                'student_id': user_id, 'user_id': user_id, 'name': user_name,
                'score': 0, 'current_question_index': 0, 'correct_count': 0,
                'wrong_count': 0, 'skipped_count': 0, 'answers': {}, 'ratings': {},
                'status': 'active', 'joined_at': get_somali_time_db()
            }
            add_participant_to_cache(quiz['id'], user_id, participant_data)
            flash('Quiz created successfully! Share the join code.', 'success')
            return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
        else:
            flash('Failed to create quiz. Please try again.', 'error')

    return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)

# ============================================
# CREATE WITH AVAILABLE - POST only
# ============================================

@live_quiz_bp.route('/create-with-available', methods=['POST'])
def create_with_available():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    # CSRF validation
    if not validate_csrf():
        flash('Invalid CSRF token. Please try again.', 'error')
        return redirect(url_for('live_quiz.create'))

    user_id = session['user_id']
    subject_code = request.form.get('subject_code', '').strip()
    question_count = int(request.form.get('question_count', 10))
    title = request.form.get('title', '').strip()
    is_public = int(request.form.get('is_public', 1))

    user_subjects = get_user_subject_list(user_id)
    allowed_codes = [s['code'] for s in user_subjects]
    if subject_code not in allowed_codes:
        flash('Subject not available.', 'error')
        return redirect(url_for('live_quiz.create'))

    questions, available = get_questions_for_subject(subject_code, question_count)
    if available == 0:
        flash('No questions available.', 'error')
        return redirect(url_for('live_quiz.create'))

    join_code = generate_unique_join_code()
    question_ids = [q['id'] for q in questions]
    data = {
        'creator_id': user_id,
        'title': title if title else '',
        'subject_code': subject_code,
        'question_count': available,
        'join_code': join_code,
        'status': 'waiting',
        'max_participants': MAX_PARTICIPANTS,
        'time_per_question': TIME_PER_QUESTION,
        'current_question_index': 0,
        'question_ids': question_ids,
        'is_public': is_public,
        'scheduled_start': None
    }
    quiz = create_live_quiz(data)
    if quiz:
        add_live_quiz_participant(quiz['id'], user_id)
        cache = get_cache()
        cache.set(get_quiz_cache_key(quiz['id']), quiz, ttl=QUIZ_STATE_TTL)
        user = get_student_by_id(user_id)
        user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant'
        participant_data = {
            'student_id': user_id, 'user_id': user_id, 'name': user_name,
            'score': 0, 'current_question_index': 0, 'correct_count': 0,
            'wrong_count': 0, 'skipped_count': 0, 'answers': {}, 'ratings': {},
            'status': 'active', 'joined_at': get_somali_time_db()
        }
        add_participant_to_cache(quiz['id'], user_id, participant_data)
        flash(f'Quiz created with {available} questions!', 'success')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
    else:
        flash('Failed to create quiz.', 'error')
    return redirect(url_for('live_quiz.create'))

@live_quiz_bp.route('/join', methods=['GET', 'POST'])
def join():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']
    if request.method == 'POST':
        if not validate_csrf():
            flash('Invalid CSRF token. Please try again.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        join_code = request.form.get('join_code', '').strip().upper()
        if not join_code:
            flash('Please enter a join code.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        join_code = join_code.replace(' ', '')
        quiz = get_active_live_quiz(join_code)
        if not quiz:
            flash('Invalid join code or quiz has already started.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        if not quiz.get('is_public', 1):
            pass  # still joinable via code
        active_quiz = get_user_active_quiz(user_id)
        if active_quiz and active_quiz != quiz['id']:
            flash('You are already in another quiz. Please leave that quiz first.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        participant = get_participant_safe(quiz['id'], user_id)
        if participant:
            if participant.get('status') == 'left':
                if quiz['status'] in ['waiting', 'scheduled']:
                    success = db_rejoin_live_quiz(quiz['id'], user_id)
                    if success:
                        participant['status'] = 'active'
                        participant['score'] = 0
                        participant['current_question_index'] = 0
                        add_participant_to_cache(quiz['id'], user_id, participant)
                        flash('You have rejoined the quiz!', 'success')
                        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
                    else:
                        flash('Failed to rejoin. Please try again.', 'error')
                else:
                    flash('Cannot rejoin an active quiz.', 'error')
                return redirect(url_for('live_quiz.lobby'))
            else:
                flash('You have already joined this quiz.', 'info')
                return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
        participant_count = get_live_quiz_count(quiz['id'])
        if participant_count >= quiz.get('max_participants', 50):
            flash('This quiz is full.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        add_live_quiz_participant(quiz['id'], user_id)
        user = get_student_by_id(user_id)
        user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant'
        participant_data = {
            'student_id': user_id, 'user_id': user_id, 'name': user_name,
            'score': 0, 'current_question_index': 0, 'correct_count': 0,
            'wrong_count': 0, 'skipped_count': 0, 'answers': {}, 'ratings': {},
            'status': 'active', 'joined_at': get_somali_time_db()
        }
        add_participant_to_cache(quiz['id'], user_id, participant_data)
        notify_participant_joined(quiz['id'], quiz.get('title', 'Live Quiz'), user_name, quiz['creator_id'])
        flash('You have joined the quiz!', 'success')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
    return render_template('dashboard/live_quiz/join.html')

@live_quiz_bp.route('/waiting-room/<quiz_id>')
def waiting_room(quiz_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']
    quiz, participant, redirect_resp = get_quiz_or_redirect(
        quiz_id, user_id, required_status=['waiting', 'scheduled'], check_participant=True, allow_creator=True
    )
    if redirect_resp:
        return redirect_resp

    is_creator = quiz['creator_id'] == user_id
    user_participant_status = participant.get('status') if participant else None
    active_participants = get_active_participants(quiz_id)
    active_participant_count = len(active_participants)
    participants_data = get_live_quiz_participants(quiz_id)
    formatted_participants = []
    for p in participants_data:
        student = p.get('student', {})
        formatted_participants.append({
            'id': p['id'], 'student_id': p['student_id'],
            'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown',
            'public_id': student.get('public_id', '----'),
            'status': p.get('status', 'active'),
            'is_creator': p['student_id'] == quiz['creator_id'],
            'is_ready': bool(p.get('is_ready', 0))
        })

    scheduled_start = quiz.get('scheduled_start')
    starts_in_seconds = None
    scheduled_start_display = None
    if scheduled_start and quiz['status'] == 'scheduled':
        try:
            start_dt = datetime.fromisoformat(scheduled_start.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            diff = (start_dt - now).total_seconds()
            starts_in_seconds = max(0, int(diff))
            scheduled_start_display = format_somali_time(start_dt)
        except Exception:
            pass

    return render_template('dashboard/live_quiz/waiting_room.html',
                         quiz=quiz, is_creator=is_creator,
                         participants=formatted_participants,
                         participant_count=active_participant_count,
                         active_participant_count=active_participant_count,
                         user_participant_status=user_participant_status,
                         starts_in_seconds=starts_in_seconds,
                         scheduled_start_display=scheduled_start_display)

@live_quiz_bp.route('/waiting-room/participants/<quiz_id>')
def waiting_room_participants(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404
    participants_data = get_live_quiz_participants(quiz_id)
    formatted = []
    for p in participants_data:
        student = p.get('student', {})
        formatted.append({
            'id': p['id'],
            'student_id': p['student_id'],
            'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown',
            'public_id': student.get('public_id', '----'),
            'status': p.get('status', 'active'),
            'is_creator': p['student_id'] == quiz['creator_id'],
            'is_ready': bool(p.get('is_ready', 0))
        })
    return jsonify({'participants': formatted, 'count': len(formatted)})

@live_quiz_bp.route('/toggle-ready/<quiz_id>', methods=['POST'])
def toggle_ready(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    data = request.get_json()
    is_ready = data.get('is_ready', False)

    participant = get_live_quiz_participant(quiz_id, user_id)
    if not participant:
        return jsonify({'error': 'Not a participant'}), 404

    success = update_participant_ready(quiz_id, user_id, is_ready)
    if success:
        invalidate_quiz_cache(quiz_id)
        return jsonify({'success': True, 'is_ready': is_ready})
    return jsonify({'error': 'Failed to update ready status'}), 500

@live_quiz_bp.route('/start/<quiz_id>', methods=['POST'])
def start_quiz(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404
    if quiz['creator_id'] != user_id:
        return jsonify({'error': 'Only the creator can start the quiz'}), 403
    if quiz['status'] not in ['waiting', 'scheduled']:
        return jsonify({'error': 'Quiz already started or finished'}), 400
    active_participants = get_active_participants(quiz_id)
    active_count = len(active_participants)
    if active_count < 2:
        return jsonify({'error': 'Need at least 2 active participants to start'}), 400
    update_live_quiz(quiz_id, {'status': 'active', 'started_at': get_somali_time_db(), 'scheduled_start': None})
    cache = get_cache()
    quiz['status'] = 'active'
    quiz['started_at'] = get_somali_time_db()
    quiz['scheduled_start'] = None
    cache.set(get_quiz_cache_key(quiz_id), quiz, ttl=QUIZ_STATE_TTL)
    participants = get_live_quiz_participants(quiz_id)
    for p in participants:
        if p['status'] != 'left':
            student = get_student_by_id(p['student_id'])
            name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant' if student else 'Participant'
            updates = {'current_question_index': 0, 'score': 0, 'correct_count': 0, 'wrong_count': 0, 'skipped_count': 0, 'answers': {}, 'ratings': {}}
            update_live_quiz_participant(p['id'], updates)
            update_participant_async(quiz_id, p['student_id'], updates)
    notify_live_quiz_start(quiz_id, quiz.get('title', 'Live Quiz'), participants)
    return jsonify({'success': True, 'quiz_id': quiz_id, 'redirect_url': url_for('live_quiz.play', quiz_id=quiz_id)})

@live_quiz_bp.route('/quiz-state/<quiz_id>')
def quiz_state(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    user_id = session['user_id']

    quiz, participant, redirect_resp = get_quiz_or_redirect(
        quiz_id, user_id, required_status=['waiting', 'scheduled', 'active', 'finished'],
        check_participant=True, allow_creator=True
    )
    if redirect_resp:
        location = redirect_resp.headers.get('Location', url_for('live_quiz.lobby'))
        return jsonify({'error': 'Quiz not available', 'abort': True, 'redirect': location, 'message': 'Quiz is not available in its current state'}), 404

    try:
        # --- SCHEDULING LOGIC ---
        if quiz.get('status') == 'scheduled' and quiz.get('scheduled_start'):
            try:
                start_dt = datetime.fromisoformat(quiz['scheduled_start'].replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                diff = (start_dt - now).total_seconds()
                starts_in_seconds = max(0, int(diff))
                if starts_in_seconds <= 0:
                    all_participants = get_live_quiz_participants(quiz_id)
                    active_participants = [p for p in all_participants if p.get('status') != 'left']
                    if len(active_participants) < 2:
                        update_live_quiz(quiz_id, {'status': 'waiting', 'scheduled_start': None})
                        cache = get_cache()
                        cache.delete(get_quiz_cache_key(quiz_id))
                        create_notification(
                            user_id=quiz['creator_id'],
                            type='scheduled_skipped',
                            title='⏰ Scheduled Quiz Skipped',
                            body=f'Your quiz "{quiz.get("title", "Live Quiz")}" did not have enough participants to auto-start. It is now available for manual start.',
                            link=f'/live-quiz/waiting-room/{quiz_id}',
                            icon='⏰'
                        )
                        quiz = get_live_quiz_with_subject(quiz_id)
                        return jsonify({'status': 'waiting', 'message': 'Scheduled start skipped due to insufficient participants'})
                    else:
                        update_live_quiz(quiz_id, {'status': 'active', 'started_at': get_somali_time_db(), 'scheduled_start': None})
                        cache = get_cache()
                        quiz['status'] = 'active'
                        quiz['started_at'] = get_somali_time_db()
                        quiz['scheduled_start'] = None
                        cache.set(get_quiz_cache_key(quiz_id), quiz, ttl=QUIZ_STATE_TTL)
                        participants = get_live_quiz_participants(quiz_id)
                        for p in participants:
                            if p['status'] != 'left':
                                updates = {'current_question_index': 0, 'score': 0, 'correct_count': 0, 'wrong_count': 0, 'skipped_count': 0, 'answers': {}, 'ratings': {}}
                                update_live_quiz_participant(p['id'], updates)
                                update_participant_async(quiz_id, p['student_id'], updates)
                        notify_live_quiz_start(quiz_id, quiz.get('title', 'Live Quiz'), participants)
                        return jsonify({'status': 'active', 'redirect_url': url_for('live_quiz.play', quiz_id=quiz_id)})
                else:
                    return jsonify({'status': 'scheduled', 'starts_in_seconds': starts_in_seconds})
            except Exception as e:
                logging.getLogger(__name__).error(f"Schedule transition error: {e}")

        # --- NORMAL STATE LOGIC ---
        question_ids = quiz.get('question_ids', [])
        if quiz.get('status') == 'active' and len(question_ids) == 0:
            finalize_live_quiz(quiz_id)
            return jsonify({'status': 'finished', 'remaining_time': 0, 'redirect_url': url_for('live_quiz.results', quiz_id=quiz_id)})

        answers = participant.get('answers', {})
        shuffled_ids = answers.get('__shuffled_ids')
        if not shuffled_ids:
            shuffled_ids = quiz.get('question_ids', [])

        current_index = participant.get('current_question_index', 0)
        total_questions = len(shuffled_ids)

        if quiz.get('status') == 'active' and current_index >= total_questions and total_questions > 0:
            pass

        all_participants = get_participants_from_cache(quiz_id)
        if all_participants is None:
            all_participants = []
            db_participants = get_live_quiz_participants_with_names(quiz_id)
            for p in db_participants:
                student = p.get('student', {})
                all_participants.append({
                    'student_id': p.get('student_id'),
                    'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown',
                    'score': p.get('score', 0),
                    'current_question_index': p.get('current_question_index', 0),
                    'correct_count': p.get('correct_count', 0),
                    'wrong_count': p.get('wrong_count', 0),
                    'skipped_count': p.get('skipped_count', 0),
                    'status': p.get('status', 'active')
                })

        active_participants = [p for p in all_participants if p.get('status') != 'left']
        active_count = len(active_participants)

        time_per_question = quiz.get('time_per_question', TIME_PER_QUESTION)
        rating_time = RATING_TIME
        total_duration = total_questions * (time_per_question + rating_time)

        started_at = quiz.get('started_at')
        remaining = total_duration
        if started_at and quiz.get('status') == 'active':
            try:
                if isinstance(started_at, str):
                    started = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                else:
                    started = started_at
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                remaining = max(0, total_duration - elapsed)
            except Exception:
                remaining = total_duration

        if quiz.get('status') == 'active':
            if active_count == 0:
                finalize_live_quiz(quiz_id)
                return jsonify({'status': 'finished', 'remaining_time': 0, 'redirect_url': url_for('live_quiz.results', quiz_id=quiz_id)})
            if quiz.get('started_at') is None:
                finalize_live_quiz(quiz_id)
                return jsonify({'status': 'finished', 'remaining_time': 0, 'redirect_url': url_for('live_quiz.results', quiz_id=quiz_id)})

        if remaining <= 0 and quiz.get('status') == 'active':
            finalize_live_quiz(quiz_id)
            return jsonify({'status': 'finished', 'remaining_time': 0, 'redirect_url': url_for('live_quiz.results', quiz_id=quiz_id)})

        completed_count = sum(1 for p in active_participants if p.get('current_question_index', 0) >= total_questions)
        all_completed = completed_count == active_count and active_count > 0

        if all_completed and quiz.get('status') == 'active' and active_count >= 1:
            finalize_live_quiz(quiz_id)
            return jsonify({'status': 'finished', 'remaining_time': 0, 'redirect_url': url_for('live_quiz.results', quiz_id=quiz_id)})

        is_completed = current_index >= total_questions

        response = {
            'status': quiz.get('status'),
            'total_duration': total_duration,
            'remaining_time': int(remaining),
            'completed_count': completed_count,
            'total_participants': active_count,
            'is_completed': is_completed,
            'current_question_index': current_index,
            'total_questions': total_questions,
            'all_completed': all_completed,
            'score': participant.get('score', 0),
            'current_question_answered': False,
            'current_question_answer': None,
            'current_question_correct': False,
            'active_participants': active_count
        }

        if current_index < len(shuffled_ids):
            qid = shuffled_ids[current_index]
            answers = participant.get('answers', {})
            if str(qid) in answers:
                response['current_question_answered'] = True
                response['current_question_answer'] = answers[str(qid)].get('answer')
                response['current_question_correct'] = answers[str(qid)].get('correct', False)

        if quiz.get('creator_id') == user_id:
            progress = []
            for p in all_participants:
                progress.append({
                    'user_id': p.get('student_id'),
                    'name': p.get('name', 'Unknown'),
                    'current_question_index': p.get('current_question_index', 0),
                    'total_questions': total_questions,
                    'status': p.get('status', 'active'),
                    'score': p.get('score', 0)
                })
            response['participant_progress'] = progress

        if quiz.get('status') == 'finished':
            response['redirect_url'] = url_for('live_quiz.results', quiz_id=quiz_id)

        return jsonify(response)

    except Exception as e:
        logging.getLogger(__name__).error(f"Error in quiz_state: {e}", exc_info=True)
        return jsonify({'error': 'Server error loading quiz state', 'abort': True, 'redirect': url_for('live_quiz.lobby'), 'message': 'An error occurred loading the quiz'}), 500

@live_quiz_bp.route('/get-question/<quiz_id>')
def get_question(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    user_id = session['user_id']
    quiz, participant, redirect_resp = get_quiz_or_redirect(
        quiz_id, user_id, required_status='active', check_participant=True
    )
    if redirect_resp:
        location = redirect_resp.headers.get('Location', url_for('live_quiz.lobby'))
        return jsonify({'error': 'Quiz not available', 'abort': True, 'redirect': location, 'message': 'Quiz is not active or you are not a participant'}), 404
    try:
        answers = participant.get('answers', {})
        shuffled_ids = answers.get('__shuffled_ids')
        if not shuffled_ids:
            shuffled_ids = quiz.get('question_ids', [])

        current_index = participant.get('current_question_index', 0)
        total_questions = len(shuffled_ids)

        if current_index >= total_questions:
            return jsonify({'completed': True})

        if current_index >= len(shuffled_ids):
            return jsonify({'completed': True})

        question_id = shuffled_ids[current_index]

        if str(question_id) in answers:
            answer_data = answers[str(question_id)]
            is_correct = answer_data.get('correct', False)
            question = get_question_by_id(question_id)
            if question:
                return jsonify({
                    'question': question, 'index': current_index, 'total': total_questions,
                    'already_answered': True, 'answer': answer_data.get('answer'),
                    'correct': is_correct, 'correct_answer': question.get('correct_answer'),
                    'explanation': question.get('explanation', '')
                })
            else:
                new_index = current_index + 1
                update_participant_async(quiz_id, user_id, {'current_question_index': new_index})
                return jsonify({'skipped': True})

        ratings = participant.get('ratings', {})
        if str(question_id) in ratings:
            new_index = current_index + 1
            update_participant_async(quiz_id, user_id, {'current_question_index': new_index})
            return jsonify({'skipped': True})

        question = get_question_by_id(question_id)
        if not question:
            new_index = current_index + 1
            update_participant_async(quiz_id, user_id, {'current_question_index': new_index})
            return jsonify({'skipped': True})

        return jsonify({'question': question, 'index': current_index, 'total': total_questions, 'already_answered': False})
    except Exception as e:
        logging.getLogger(__name__).error(f"Error in get_question: {e}", exc_info=True)
        return jsonify({'error': 'Server error loading question', 'abort': True, 'redirect': url_for('live_quiz.lobby'), 'message': 'An error occurred loading the question'}), 500

@live_quiz_bp.route('/submit-answer', methods=['POST'])
def submit_answer():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')
    answer = data.get('answer')
    if not quiz_id or not question_id or not answer:
        return jsonify({'error': 'Missing required fields'}), 400
    try:
        # Check quiz is active
        quiz = get_live_quiz_by_id(quiz_id)
        if not quiz or quiz.get('status') != 'active':
            return jsonify({'error': 'Quiz is not active'}), 400

        # Verify question belongs to this quiz
        question_ids = quiz.get('question_ids', [])
        if question_id not in question_ids:
            return jsonify({'error': 'Question does not belong to this quiz'}), 400

        participant = get_participant_safe(quiz_id, user_id)
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404

        # Check if already answered this question
        answers = participant.get('answers', {})
        if str(question_id) in answers:
            return jsonify({'error': 'Already answered this question'}), 400

        question = get_question_by_id(question_id)
        if not question:
            return jsonify({'error': 'Question not found'}), 404

        is_correct = answer == question['correct_answer']
        score = participant.get('score', 0)
        correct_count = participant.get('correct_count', 0)
        wrong_count = participant.get('wrong_count', 0)
        if is_correct:
            score += 2
            correct_count += 1
        else:
            wrong_count += 1

        answers[str(question_id)] = {'answer': answer, 'correct': is_correct}
        updates = {'answers': answers, 'score': score, 'correct_count': correct_count, 'wrong_count': wrong_count}
        update_participant_async(quiz_id, user_id, updates)

        return jsonify({'correct': is_correct, 'correct_answer': question['correct_answer'], 'explanation': question.get('explanation', '')})
    except Exception as e:
        logging.getLogger(__name__).error(f"Error in submit_answer: {e}", exc_info=True)
        return jsonify({'error': 'Failed to submit answer'}), 500

@live_quiz_bp.route('/skip-question', methods=['POST'])
def skip_question():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')
    if not quiz_id or not question_id:
        return jsonify({'error': 'Missing required fields'}), 400
    try:
        quiz = get_live_quiz_by_id(quiz_id)
        if not quiz or quiz.get('status') != 'active':
            return jsonify({'error': 'Quiz is not active'}), 400

        question_ids = quiz.get('question_ids', [])
        if question_id not in question_ids:
            return jsonify({'error': 'Question does not belong to this quiz'}), 400

        participant = get_participant_safe(quiz_id, user_id)
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404

        answers = participant.get('answers', {})
        if str(question_id) in answers:
            return jsonify({'error': 'Already answered this question'}), 400

        answers[str(question_id)] = {'answer': None, 'correct': False, 'skipped': True}
        skipped_count = participant.get('skipped_count', 0) + 1
        current_index = participant.get('current_question_index', 0)
        new_index = current_index + 1
        updates = {'answers': answers, 'skipped_count': skipped_count, 'current_question_index': new_index}
        update_participant_async(quiz_id, user_id, updates)
        return jsonify({'success': True})
    except Exception as e:
        logging.getLogger(__name__).error(f"Error in skip_question: {e}", exc_info=True)
        return jsonify({'error': 'Failed to skip question'}), 500

@live_quiz_bp.route('/submit-rating', methods=['POST'])
def submit_rating():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')
    rating = data.get('rating')
    if not quiz_id or not question_id or not rating:
        return jsonify({'error': 'Missing required fields'}), 400
    if rating not in ['HAA', 'MAY']:
        return jsonify({'error': 'Invalid rating'}), 400
    try:
        quiz = get_live_quiz_by_id(quiz_id)
        if not quiz or quiz.get('status') != 'active':
            return jsonify({'error': 'Quiz is not active'}), 400

        participant = get_participant_safe(quiz_id, user_id)
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404

        answers = participant.get('answers', {})
        if str(question_id) not in answers:
            return jsonify({'error': 'You must answer the question before rating'}), 400

        ratings = participant.get('ratings', {})
        if str(question_id) in ratings:
            return jsonify({'error': 'Already rated this question'}), 400

        ratings[str(question_id)] = rating
        current_index = participant.get('current_question_index', 0)
        new_index = current_index + 1
        updates = {'ratings': ratings, 'current_question_index': new_index}
        update_participant_async(quiz_id, user_id, updates)
        return jsonify({'success': True, 'completed': new_index >= len(answers)})
    except Exception as e:
        logging.getLogger(__name__).error(f"Error in submit_rating: {e}", exc_info=True)
        return jsonify({'error': 'Failed to submit rating'}), 500

@live_quiz_bp.route('/leaderboard/<quiz_id>')
def get_leaderboard(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    user_id = session['user_id']
    try:
        leaderboard = get_leaderboard_from_cache(quiz_id, 10)
        user_rank = None
        for i, item in enumerate(leaderboard, 1):
            if item.get('user_id') == user_id or item.get('student_id') == user_id:
                user_rank = i
                break
        return jsonify({'leaderboard': leaderboard, 'user_rank': user_rank})
    except Exception as e:
        logging.getLogger(__name__).error(f"Error in leaderboard: {e}", exc_info=True)
        return jsonify({'error': 'Failed to load leaderboard'}), 500

@live_quiz_bp.route('/play/<quiz_id>')
def play(quiz_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']
    quiz, participant, redirect_resp = get_quiz_or_redirect(
        quiz_id, user_id, required_status='active', check_participant=True
    )
    if redirect_resp:
        return redirect_resp
    return render_template('dashboard/live_quiz/play.html', quiz=quiz)

@live_quiz_bp.route('/leave/<quiz_id>', methods=['POST'])
def leave_quiz(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404
    if quiz['status'] == 'finished':
        return jsonify({'error': 'Quiz already finished'}), 400
    participant = get_participant_safe(quiz_id, user_id)
    if not participant:
        return jsonify({'error': 'Not a participant'}), 404
    if participant.get('status') == 'left':
        return jsonify({'error': 'Already left this quiz'}), 400
    if quiz['creator_id'] == user_id:
        return jsonify({'error': 'Creator cannot leave the quiz'}), 400
    success = db_leave_live_quiz(quiz_id, user_id)
    if success:
        update_participant_async(quiz_id, user_id, {'status': 'left'})
        invalidate_quiz_cache(quiz_id)
        return jsonify({'success': True, 'message': 'You have left the quiz', 'redirect': url_for('live_quiz.lobby')})
    return jsonify({'error': 'Failed to leave quiz'}), 500

@live_quiz_bp.route('/rejoin/<quiz_id>', methods=['POST'])
def rejoin_quiz(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404
    if quiz['status'] not in ['waiting', 'scheduled']:
        return jsonify({'error': 'Quiz is not open for rejoining'}), 400
    participant = get_participant_safe(quiz_id, user_id)
    if not participant or participant.get('status') != 'left':
        return jsonify({'error': 'You are not eligible to rejoin'}), 400
    success = db_rejoin_live_quiz(quiz_id, user_id)
    if success:
        update_participant_async(quiz_id, user_id, {'status': 'active'})
        invalidate_quiz_cache(quiz_id)
        return jsonify({'success': True, 'message': 'You have rejoined the quiz', 'redirect': url_for('live_quiz.waiting_room', quiz_id=quiz_id)})
    return jsonify({'error': 'Failed to rejoin quiz'}), 500

@live_quiz_bp.route('/delete/<quiz_id>', methods=['POST'])
def delete_quiz(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    user_id = session['user_id']
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404
    if quiz['creator_id'] != user_id and not is_admin(user_id):
        return jsonify({'error': 'Permission denied'}), 403
    invalidate_quiz_cache(quiz_id)
    success = db_delete_live_quiz(quiz_id)
    if success:
        return jsonify({'success': True, 'message': 'Quiz deleted'})
    return jsonify({'error': 'Failed to delete quiz'}), 500

@live_quiz_bp.route('/results/<quiz_id>')
def results(quiz_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']
    quiz, participant, redirect_resp = get_quiz_or_redirect(
        quiz_id, user_id, required_status='finished', check_participant=True, allow_creator=True
    )
    if redirect_resp:
        return redirect_resp
    if quiz.get('status') != 'finished':
        finalize_live_quiz(quiz_id)
        quiz = get_live_quiz_with_subject(quiz_id)
    is_creator = quiz['creator_id'] == user_id
    all_participants = get_live_quiz_participants_with_names(quiz_id)
    sorted_participants = sorted(all_participants, key=lambda x: x.get('score', 0), reverse=True)
    for i, p in enumerate(sorted_participants, 1):
        if p.get('ranking') != i:
            update_live_quiz_participant(p['id'], {'ranking': i})
            p['ranking'] = i
    user_participant = None
    for p in sorted_participants:
        if p['student_id'] == user_id:
            user_participant = p
            break
    return render_template('dashboard/live_quiz/results.html',
                         quiz=quiz, is_creator=is_creator,
                         participants=sorted_participants,
                         user_participant=user_participant)

@live_quiz_bp.route('/analysis/<quiz_id>')
def analysis(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    user_id = session['user_id']
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404
    if quiz['creator_id'] != user_id:
        return jsonify({'error': 'Only the creator can view analysis'}), 403
    question_ids = quiz.get('question_ids', [])
    participants = get_live_quiz_participants(quiz_id)
    analysis_data = []
    for i, qid in enumerate(question_ids):
        correct_count = 0
        total_count = 0
        for p in participants:
            answers = p.get('answers', {})
            if str(qid) in answers:
                total_count += 1
                if answers[str(qid)].get('correct', False):
                    correct_count += 1
        question = get_question_by_id(qid)
        q_text = question.get('question_text', 'Unknown') if question else 'Unknown'
        correct_rate = round((correct_count / total_count) * 100) if total_count > 0 else 0
        wrong_rate = 100 - correct_rate
        analysis_data.append({'index': i, 'text': q_text, 'correct_rate': correct_rate, 'wrong_rate': wrong_rate, 'total_answers': total_count})
    most_correct = sorted(analysis_data, key=lambda x: x['correct_rate'], reverse=True)[:3]
    most_wrong = sorted(analysis_data, key=lambda x: x['wrong_rate'], reverse=True)[:3]
    return jsonify({'most_correct': most_correct, 'most_wrong': most_wrong})

@live_quiz_bp.route('/export/<quiz_id>')
def export_results(quiz_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.index'))
    if quiz['creator_id'] != user_id:
        flash('Only the creator can export results.', 'error')
        return redirect(url_for('live_quiz.index'))
    participants = get_live_quiz_participants_with_names(quiz_id)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Rank', 'Name', 'Public ID', 'Score', 'Correct', 'Wrong', 'Skipped', 'Status'])
    sorted_participants = sorted(participants, key=lambda x: x.get('score', 0), reverse=True)
    for i, p in enumerate(sorted_participants, 1):
        student = p.get('student', {})
        name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown'
        writer.writerow([i, name, student.get('public_id', '----'), p.get('score', 0), p.get('correct_count', 0), p.get('wrong_count', 0), p.get('skipped_count', 0), p.get('status', 'active')])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=quiz_{quiz_id}_results.csv'})

@live_quiz_bp.route('/flush-cache', methods=['POST'])
def flush_cache_endpoint():
    if 'user_id' not in session or not is_admin(session['user_id']):
        return jsonify({'error': 'Unauthorized'}), 403
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    try:
        cache = get_cache()
        cache.invalidate_pattern('quiz:*')
        return jsonify({'success': True, 'message': 'Quiz cache flushed'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@live_quiz_bp.route('/cache-stats')
def cache_stats():
    if 'user_id' not in session or not is_admin(session['user_id']):
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        cache = get_cache()
        stats = cache.get_metrics()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500