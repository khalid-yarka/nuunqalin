# blueprints/live_quiz_bp.py
"""
Live Quiz Blueprint – Redis‑first state management.
All active quiz state is stored in Redis (authoritative).
SQLite is used for base data, checkpoints, and final results.
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
    create_live_quiz_with_participant,
    generate_unique_join_code,
    execute_with_retry,
)

from config import Config
from utils import get_somali_time_db, get_somali_time_display, format_somali_time, validate_csrf, ensure_csrf_token
from subjects_config import get_subject, get_all_subjects

from cache import get_cache_manager, InvalidationHelper, make_key
from cache.worker import STREAM_KEY as CACHE_STREAM_KEY
from redis_state import LiveQuizState  # NEW: Redis state manager

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

logger = logging.getLogger(__name__)

def get_cache():
    return get_cache_manager()

# Redis state manager instance
_state_manager = None
def get_state_manager():
    global _state_manager
    if _state_manager is None:
        _state_manager = LiveQuizState(get_redis_client())
    return _state_manager

# --------------------------------------------
#  Helper: invalidate old cache (still used for other caches)
# --------------------------------------------
def invalidate_quiz_cache(quiz_id: int):
    InvalidationHelper.invalidate_quiz(quiz_id)
    cache = get_cache()
    cache.invalidate_pattern(f"quiz:*:{quiz_id}:*")

# --------------------------------------------
#  Routes
# --------------------------------------------

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

    # Get quiz from DB (base metadata)
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404

    # Check if user can join
    can_join, reason = can_join_live_quiz(quiz_id, user_id)
    if not can_join:
        return jsonify({'error': reason}), 400

    # Add participant to DB (this is durable; Redis will sync later)
    success = add_live_quiz_participant(quiz_id, user_id)
    if not success:
        return jsonify({'error': 'Failed to join quiz'}), 500

    # Initialize participant in Redis state
    state = get_state_manager()
    state.init_participant(
        quiz_id=quiz_id,
        user_id=user_id,
        question_ids=quiz.get('question_ids', [])
    )

    # Notify creator
    user = get_student_by_id(user_id)
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant'
    notify_participant_joined(quiz_id, quiz.get('title', 'Live Quiz'), user_name, quiz['creator_id'])

    return jsonify({
        'success': True,
        'redirect': url_for('live_quiz.waiting_room', quiz_id=quiz_id)
    })

@live_quiz_bp.route('/create', methods=['GET', 'POST'])
def create():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user_subjects = get_user_subject_list(user_id)
    
    if not user_subjects:
        flash('You need to set your location and curriculum in your profile before creating a quiz.', 'error')
        return redirect(url_for('dashboard.profile'))
    
    if request.method == 'GET':
        ensure_csrf_token()
    
    if request.method == 'POST':
        if not validate_csrf():
            flash('Invalid CSRF token. Please try again.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)
        
        subject_code = request.form.get('subject_code', '').strip()
        allowed_codes = [s['code'] for s in user_subjects]
        if subject_code not in allowed_codes:
            flash('Subject not available for your location/curriculum.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)
        
        try:
            question_count = int(request.form.get('question_count', 10))
        except ValueError:
            question_count = 10
        if question_count < 5 or question_count > 30:
            flash('Number of questions must be between 5 and 30.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects,
                                   subject_code=subject_code, title=request.form.get('title', '').strip(),
                                   is_public=request.form.get('is_public', 1))
        
        title = request.form.get('title', '').strip()
        if len(title) > 100:
            flash('Title is too long (max 100 characters).', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects,
                                   subject_code=subject_code, title=title, is_public=request.form.get('is_public', 1))
        
        try:
            is_public = int(request.form.get('is_public', 1))
        except ValueError:
            is_public = 1
        if is_public not in (0, 1):
            is_public = 1
        
        try:
            schedule_minutes = int(request.form.get('schedule_minutes', 0))
        except ValueError:
            schedule_minutes = 0
        if schedule_minutes < 0:
            schedule_minutes = 0
        
        try:
            questions, available = get_questions_for_subject(subject_code, question_count)
        except Exception as e:
            logger.error(f"Error fetching questions for subject {subject_code}: {e}", exc_info=True)
            flash('Error fetching questions. Please try again.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects,
                                   subject_code=subject_code, title=title, is_public=is_public)
        
        if available == 0:
            flash('No questions available for this subject. Please select another subject.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)
        
        if available < question_count:
            return render_template('dashboard/live_quiz/create.html',
                                   subjects=user_subjects, not_enough=True,
                                   available=available, requested=question_count,
                                   subject_code=subject_code, title=title, is_public=is_public)
        
        question_ids = [q['id'] for q in questions]
        
        quiz_data = {
            'creator_id': user_id,
            'title': title,
            'subject_code': subject_code,
            'question_count': question_count,
            'max_participants': MAX_PARTICIPANTS,
            'time_per_question': TIME_PER_QUESTION,
            'current_question_index': 0,
            'question_ids': question_ids,
            'is_public': is_public,
        }
        
        if schedule_minutes > 0:
            quiz_data['status'] = 'scheduled'
            scheduled_time = datetime.now(timezone.utc) + timedelta(minutes=schedule_minutes)
            quiz_data['scheduled_start'] = scheduled_time.isoformat()
        else:
            quiz_data['status'] = 'waiting'
            quiz_data['scheduled_start'] = None
        
        quiz, error = create_live_quiz_with_participant(quiz_data, user_id)
        
        if error or not quiz:
            flash(f'Failed to create quiz: {error or "Unknown error"}', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=user_subjects,
                                   subject_code=subject_code, title=title, is_public=is_public)
        
        if not quiz.get('id'):
            logger.error(f"Quiz created but missing 'id': {quiz}")
            flash('Quiz created but missing ID. Please contact support.', 'error')
            return redirect(url_for('live_quiz.lobby'))
        
        # Initialise Redis state for the creator
        state = get_state_manager()
        state.init_participant(quiz['id'], user_id, quiz.get('question_ids', []))
        
        # Also set name and public_id
        user = get_student_by_id(user_id)
        if user:
            state.update_participant(quiz['id'], user_id, {
                'name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant',
                'public_id': user.get('public_id', '----')
            })
        
        # Cache quiz metadata in old cache (for lobby)
        try:
            cache = get_cache()
            cache.set(make_key('quiz', 'state', str(quiz['id'])), quiz, ttl=QUIZ_STATE_TTL)
        except Exception as e:
            logger.error(f"Error caching quiz: {e}", exc_info=True)
        
        flash('Quiz created successfully! Share the join code.', 'success')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
    
    return render_template('dashboard/live_quiz/create.html', subjects=user_subjects)

@live_quiz_bp.route('/create-with-available', methods=['POST'])
def create_with_available():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    if not validate_csrf():
        flash('Invalid CSRF token. Please try again.', 'error')
        return redirect(url_for('live_quiz.create'))

    user_id = session['user_id']
    subject_code = request.form.get('subject_code', '').strip()
    try:
        question_count = int(request.form.get('question_count', 10))
    except ValueError:
        question_count = 10
    if question_count < 5 or question_count > 30:
        flash('Number of questions must be between 5 and 30.', 'error')
        return redirect(url_for('live_quiz.create'))

    title = request.form.get('title', '').strip()
    if len(title) > 100:
        flash('Title is too long (max 100 characters).', 'error')
        return redirect(url_for('live_quiz.create'))

    try:
        is_public = int(request.form.get('is_public', 1))
    except ValueError:
        is_public = 1
    if is_public not in (0, 1):
        is_public = 1

    user_subjects = get_user_subject_list(user_id)
    allowed_codes = [s['code'] for s in user_subjects]
    if subject_code not in allowed_codes:
        flash('Subject not available.', 'error')
        return redirect(url_for('live_quiz.create'))

    questions, available = get_questions_for_subject(subject_code, question_count)
    if available == 0:
        flash('No questions available.', 'error')
        return redirect(url_for('live_quiz.create'))

    question_ids = [q['id'] for q in questions]
    quiz_data = {
        'creator_id': user_id,
        'title': title,
        'subject_code': subject_code,
        'question_count': available,
        'max_participants': MAX_PARTICIPANTS,
        'time_per_question': TIME_PER_QUESTION,
        'current_question_index': 0,
        'question_ids': question_ids,
        'is_public': is_public,
        'status': 'waiting',
        'scheduled_start': None
    }

    quiz, error = create_live_quiz_with_participant(quiz_data, user_id)
    if error or not quiz:
        flash(f'Failed to create quiz: {error or "Unknown error"}', 'error')
        return redirect(url_for('live_quiz.create'))

    # Initialise Redis state for the creator
    state = get_state_manager()
    state.init_participant(quiz['id'], user_id, quiz.get('question_ids', []))
    user = get_student_by_id(user_id)
    if user:
        state.update_participant(quiz['id'], user_id, {
            'name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant',
            'public_id': user.get('public_id', '----')
        })

    cache = get_cache()
    cache.set(make_key('quiz', 'state', str(quiz['id'])), quiz, ttl=QUIZ_STATE_TTL)

    flash(f'Quiz created with {available} questions!', 'success')
    return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))

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
        active_quiz = get_user_active_quiz(user_id)
        if active_quiz and active_quiz != quiz['id']:
            flash('You are already in another quiz. Please leave that quiz first.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        participant = get_live_quiz_participant(quiz['id'], user_id)  # fallback DB check
        if participant:
            if participant.get('status') == 'left':
                if quiz['status'] in ['waiting', 'scheduled']:
                    success = db_rejoin_live_quiz(quiz['id'], user_id)
                    if success:
                        # update Redis
                        state = get_state_manager()
                        state.update_participant(quiz['id'], user_id, {'status': 'active'})
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
        state = get_state_manager()
        state.init_participant(quiz['id'], user_id, quiz.get('question_ids', []))
        user = get_student_by_id(user_id)
        if user:
            state.update_participant(quiz['id'], user_id, {
                'name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant',
                'public_id': user.get('public_id', '----')
            })
        flash('You have joined the quiz!', 'success')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
    return render_template('dashboard/live_quiz/join.html')

@live_quiz_bp.route('/waiting-room/<quiz_id>')
def waiting_room(quiz_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.lobby'))
    # Check if user is a participant (DB fallback)
    participant = get_live_quiz_participant(quiz_id, user_id)
    if not participant and quiz['creator_id'] != user_id:
        flash('You are not a participant in this quiz.', 'error')
        return redirect(url_for('live_quiz.lobby'))

    is_creator = quiz['creator_id'] == user_id
    user_participant_status = participant.get('status') if participant else None
    active_participants = get_active_participants(quiz_id)  # DB fallback, but we'll use Redis for real-time in JS

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
                         participants=active_participants,
                         participant_count=len(active_participants),
                         active_participant_count=len(active_participants),
                         user_participant_status=user_participant_status,
                         starts_in_seconds=starts_in_seconds,
                         scheduled_start_display=scheduled_start_display)

@live_quiz_bp.route('/waiting-room/participants/<quiz_id>')
def waiting_room_participants(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    state = get_state_manager()
    participants = state.get_all_participants(quiz_id)
    formatted = []
    for p in participants:
        formatted.append({
            'id': p.get('user_id'),
            'student_id': p.get('user_id'),
            'name': p.get('name', 'Unknown'),
            'public_id': p.get('public_id', '----'),
            'status': p.get('status', 'active'),
            'is_creator': p.get('is_creator', False),
            'is_ready': p.get('is_ready', False)
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

    state = get_state_manager()
    success = state.set_participant_ready(quiz_id, user_id, is_ready)
    if success:
        # Also update DB for durability (optional, but we can update the ready flag in DB as well)
        update_participant_ready(quiz_id, user_id, is_ready)
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

    state = get_state_manager()
    active = state.get_active_participant_count(quiz_id)
    if active < 2:
        return jsonify({'error': 'Need at least 2 active participants to start'}), 400

    update_live_quiz(quiz_id, {'status': 'active', 'started_at': get_somali_time_db(), 'scheduled_start': None})
    state.start_quiz(quiz_id)

    participants = state.get_all_participants(quiz_id)
    notify_live_quiz_start(quiz_id, quiz.get('title', 'Live Quiz'), participants)

    return jsonify({'success': True, 'quiz_id': quiz_id, 'redirect_url': url_for('live_quiz.play', quiz_id=quiz_id)})

@live_quiz_bp.route('/quiz-state/<quiz_id>')
def quiz_state(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    user_id = session['user_id']

    quiz = get_live_quiz_with_subject(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404

    state = get_state_manager()
    participant = state.get_participant(quiz_id, user_id)
    if not participant and quiz['status'] != 'finished':
        # Attempt to restore from DB checkpoint
        db_participant = get_live_quiz_participant(quiz_id, user_id)
        if db_participant:
            state.init_participant(quiz_id, user_id, quiz.get('question_ids', []), db_participant)
            participant = state.get_participant(quiz_id, user_id)
        else:
            return jsonify({'error': 'Not a participant'}), 404

    question_ids = quiz.get('question_ids', [])
    total_questions = len(question_ids)
    current_index = participant.get('current_question_index', 0) if participant else 0
    score = participant.get('score', 0) if participant else 0
    answers = participant.get('answers', {}) if participant else {}

    if quiz['status'] == 'finished':
        return jsonify({'status': 'finished', 'redirect_url': url_for('live_quiz.results', quiz_id=quiz_id)})

    all_participants = state.get_all_participants(quiz_id)
    completed_count = sum(1 for p in all_participants if p.get('current_question_index', 0) >= total_questions)
    active_count = len([p for p in all_participants if p.get('status') != 'left'])
    all_completed = completed_count == active_count and active_count > 0

    if all_completed and quiz['status'] == 'active':
        finalize_live_quiz(quiz_id)
        return jsonify({'status': 'finished', 'redirect_url': url_for('live_quiz.results', quiz_id=quiz_id)})

    # Compute remaining time (if active)
    remaining_time = 0
    total_duration = total_questions * (TIME_PER_QUESTION + RATING_TIME)
    if quiz['status'] == 'active' and quiz.get('started_at'):
        try:
            started = datetime.fromisoformat(quiz['started_at'].replace('Z', '+00:00'))
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            remaining_time = max(0, total_duration - elapsed)
        except Exception:
            remaining_time = total_duration

    response = {
        'status': quiz['status'],
        'remaining_time': remaining_time,
        'total_duration': total_duration,
        'completed_count': completed_count,
        'total_participants': active_count,
        'is_completed': current_index >= total_questions,
        'current_question_index': current_index,
        'total_questions': total_questions,
        'all_completed': all_completed,
        'score': score,
        'current_question_answered': False,
        'current_question_answer': None,
        'current_question_correct': False,
        'active_participants': active_count
    }

    if current_index < total_questions:
        qid = question_ids[current_index]
        if str(qid) in answers:
            response['current_question_answered'] = True
            response['current_question_answer'] = answers[str(qid)].get('answer')
            response['current_question_correct'] = answers[str(qid)].get('correct', False)

    if quiz['creator_id'] == user_id:
        progress = []
        for p in all_participants:
            progress.append({
                'user_id': p.get('user_id'),
                'name': p.get('name', 'Unknown'),
                'current_question_index': p.get('current_question_index', 0),
                'total_questions': total_questions,
                'status': p.get('status', 'active'),
                'score': p.get('score', 0)
            })
        response['participant_progress'] = progress

    if quiz['status'] == 'finished':
        response['redirect_url'] = url_for('live_quiz.results', quiz_id=quiz_id)

    return jsonify(response)

@live_quiz_bp.route('/get-question/<quiz_id>')
def get_question(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    user_id = session['user_id']

    state = get_state_manager()
    participant = state.get_participant(quiz_id, user_id)
    if not participant:
        return jsonify({'error': 'Not a participant'}), 404

    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz or quiz['status'] != 'active':
        return jsonify({'error': 'Quiz not active'}), 400

    question_ids = quiz.get('question_ids', [])
    current_index = participant.get('current_question_index', 0)
    if current_index >= len(question_ids):
        return jsonify({'completed': True})

    qid = question_ids[current_index]
    answers = participant.get('answers', {})
    if str(qid) in answers:
        question = get_question_by_id(qid)
        if question:
            return jsonify({
                'question': question,
                'index': current_index,
                'total': len(question_ids),
                'already_answered': True,
                'answer': answers[str(qid)].get('answer'),
                'correct': answers[str(qid)].get('correct', False),
                'correct_answer': question.get('correct_answer'),
                'explanation': question.get('explanation', '')
            })
        else:
            new_index = current_index + 1
            state.update_participant(quiz_id, user_id, {'current_question_index': new_index})
            return jsonify({'skipped': True})

    ratings = participant.get('ratings', {})
    if str(qid) in ratings:
        new_index = current_index + 1
        state.update_participant(quiz_id, user_id, {'current_question_index': new_index})
        return jsonify({'skipped': True})

    question = get_question_by_id(qid)
    if not question:
        new_index = current_index + 1
        state.update_participant(quiz_id, user_id, {'current_question_index': new_index})
        return jsonify({'skipped': True})

    return jsonify({
        'question': question,
        'index': current_index,
        'total': len(question_ids),
        'already_answered': False
    })

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

    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz or quiz['status'] != 'active':
        return jsonify({'error': 'Quiz is not active'}), 400

    state = get_state_manager()
    participant = state.get_participant(quiz_id, user_id)
    if not participant:
        return jsonify({'error': 'Not a participant'}), 404

    # Use atomic Lua script
    success, result = state.submit_answer(quiz_id, user_id, question_id, answer, quiz.get('correct_answer'))
    if not success:
        return jsonify({'error': result}), 400

    return jsonify({
        'correct': result['correct'],
        'correct_answer': result['correct_answer'],
        'explanation': result['explanation']
    })

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

    state = get_state_manager()
    success, msg = state.skip_question(quiz_id, user_id, question_id)
    if not success:
        return jsonify({'error': msg}), 400
    return jsonify({'success': True})

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

    state = get_state_manager()
    success, msg = state.submit_rating(quiz_id, user_id, question_id, rating)
    if not success:
        return jsonify({'error': msg}), 400

    participant = state.get_participant(quiz_id, user_id)
    total_questions = len(get_question_ids_for_quiz(quiz_id))
    if participant.get('current_question_index', 0) >= total_questions:
        state.update_participant(quiz_id, user_id, {'status': 'completed'})

    return jsonify({'success': True, 'completed': participant.get('current_question_index', 0) >= total_questions})

@live_quiz_bp.route('/leaderboard/<quiz_id>')
def get_leaderboard(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    user_id = session['user_id']
    state = get_state_manager()
    leaderboard = state.get_leaderboard(quiz_id, limit=10)
    user_rank = state.get_user_rank(quiz_id, user_id)
    return jsonify({'leaderboard': leaderboard, 'user_rank': user_rank})

@live_quiz_bp.route('/play/<quiz_id>')
def play(quiz_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.lobby'))
    participant = get_live_quiz_participant(quiz_id, user_id)
    if not participant and quiz['creator_id'] != user_id:
        flash('You are not a participant in this quiz.', 'error')
        return redirect(url_for('live_quiz.lobby'))
    if quiz['status'] != 'active':
        flash('Quiz is not active.', 'error')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz_id))
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
    participant = get_live_quiz_participant(quiz_id, user_id)
    if not participant:
        return jsonify({'error': 'Not a participant'}), 404
    if participant.get('status') == 'left':
        return jsonify({'error': 'Already left this quiz'}), 400
    if quiz['creator_id'] == user_id:
        return jsonify({'error': 'Creator cannot leave the quiz'}), 400
    success = db_leave_live_quiz(quiz_id, user_id)
    if success:
        state = get_state_manager()
        state.update_participant(quiz_id, user_id, {'status': 'left'})
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
    participant = get_live_quiz_participant(quiz_id, user_id)
    if not participant or participant.get('status') != 'left':
        return jsonify({'error': 'You are not eligible to rejoin'}), 400
    success = db_rejoin_live_quiz(quiz_id, user_id)
    if success:
        state = get_state_manager()
        state.update_participant(quiz_id, user_id, {'status': 'active'})
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
    state = get_state_manager()
    state.delete_quiz(quiz_id)
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
    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.lobby'))
    if quiz['status'] != 'finished':
        # If not finished, finalize it now (in case it wasn't auto-finalized)
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

# --------------------------------------------
#  Helper: get questions for subject
# --------------------------------------------
def get_questions_for_subject(subject_code, limit):
    questions = get_questions_by_subject(subject_code, limit)
    return questions, len(questions)

# --------------------------------------------
#  Helper: finalize quiz (write final results to DB)
# --------------------------------------------
def finalize_live_quiz(quiz_id: int) -> dict:
    state = get_state_manager()
    participants = state.get_all_participants(quiz_id)
    if not participants:
        participants = get_live_quiz_participants_with_names(quiz_id)

    sorted_parts = sorted(participants, key=lambda x: x.get('score', 0), reverse=True)
    for i, p in enumerate(sorted_parts, 1):
        p['ranking'] = i

    # Update quiz status
    update_live_quiz(quiz_id, {'status': 'finished', 'ended_at': get_somali_time_db()})
    # Update each participant
    for p in sorted_parts:
        # p may be dict from Redis; if from DB, it has 'id' key
        if 'id' not in p:
            # Try to get DB participant id
            db_p = get_live_quiz_participant(quiz_id, p.get('user_id'))
            if db_p:
                p['id'] = db_p['id']
        if 'id' in p:
            update_live_quiz_participant(p['id'], {
                'score': p.get('score', 0),
                'ranking': p['ranking'],
                'answers': p.get('answers', {}),
                'ratings': p.get('ratings', {}),
                'status': 'completed'
            })

    notify_live_quiz_results(quiz_id, 'Quiz finished', sorted_parts)

    state.delete_quiz(quiz_id)
    invalidate_quiz_cache(quiz_id)

    return {'success': True, 'participants': sorted_parts}