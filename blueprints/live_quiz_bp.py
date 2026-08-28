from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify, Response
from db import (
    get_all_subjects, create_live_quiz, get_live_quiz_by_code,
    get_live_quiz_with_subject, get_live_quiz_participants,
    get_live_quiz_participant, add_live_quiz_participant,
    update_live_quiz, update_live_quiz_participant,
    get_live_quiz_participants_with_names, get_live_quiz_count,
    get_live_quiz_completed_count, get_question_ids_for_quiz,
    get_questions_by_ids, get_question_by_id, update_participant_rankings,
    get_live_quiz_creator_id, get_active_live_quiz,
    get_live_quiz_by_id, get_questions_by_subject, is_admin,
    get_student_by_id,
    notify_live_quiz_start, notify_live_quiz_results, notify_participant_joined
)
from config import Config
from utils import get_somali_time_db, get_somali_time_display
import secrets
import string
import random
import csv
from io import StringIO
from datetime import datetime, timezone
import time
import threading

# ============================================
# IMPORT QUIZ CACHE
# ============================================

from quiz_cache import get_quiz_cache, flush_cache, cleanup_cache

live_quiz_bp = Blueprint('live_quiz', __name__, url_prefix='/live-quiz')


# ============================================
# HELPER FUNCTIONS — SAFE DB + CACHE ACCESS
# ============================================

def get_quiz_safe(quiz_id: int):
    """
    Retrieve quiz from cache if available, otherwise from SQLite.
    Always returns the quiz dict (with question_ids parsed), or None.
    """
    cache = get_quiz_cache()
    quiz = cache.get_quiz(quiz_id)
    if quiz is None:
        # Fallback to DB
        quiz = get_live_quiz_by_id(quiz_id)
        if quiz:
            # Populate cache for future requests
            cache.create_quiz(quiz_id, quiz)
    return quiz


def get_participant_safe(quiz_id: int, user_id: int):
    """
    Retrieve participant from cache first, then DB.
    Ensures that the name is stored in the cache if missing.
    """
    cache = get_quiz_cache()
    participant = cache.get_participant(quiz_id, user_id)
    if participant is None:
        # Load from DB
        participant = get_live_quiz_participant(quiz_id, user_id)
        if participant:
            # Ensure name is present
            student = get_student_by_id(user_id)
            name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant' if student else 'Participant'
            participant['name'] = name
            # Add to cache
            cache.add_participant(quiz_id, user_id, participant)
    else:
        # Ensure name is present even in cached version
        if 'name' not in participant or participant['name'] == 'Participant':
            student = get_student_by_id(user_id)
            if student:
                name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant'
                participant['name'] = name
                cache.update_participant(quiz_id, user_id, {'name': name})
    return participant


def update_participant_safe(quiz_id: int, user_id: int, updates: dict):
    """
    Update participant data in SQLite first, then update cache.
    Returns the updated participant dict or None if not found.
    """
    # 1. Load current participant from DB
    participant = get_live_quiz_participant(quiz_id, user_id)
    if not participant:
        return None

    # 2. Apply updates to the DB record
    # We need to update only the fields provided.
    # The update_live_quiz_participant function expects participant_id and updates dict.
    update_live_quiz_participant(participant['id'], updates)

    # 3. Refresh the participant data from DB to get the full updated row
    updated = get_live_quiz_participant(quiz_id, user_id)
    if updated:
        # 4. Update cache
        cache = get_quiz_cache()
        cache.update_participant(quiz_id, user_id, updates)
        # Also ensure the cache has the full participant data if needed
        # We can just add the updated dict (with name) again
        student = get_student_by_id(user_id)
        name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant' if student else 'Participant'
        updated['name'] = name
        cache.add_participant(quiz_id, user_id, updated)
        return updated
    return None


def get_all_participants_safe(quiz_id: int):
    """
    Get all participants for a quiz, using cache if possible, otherwise DB.
    Returns a list of participant dicts.
    """
    cache = get_quiz_cache()
    participants = cache.get_all_participants(quiz_id)
    if not participants:
        # Load from DB and fill cache
        db_participants = get_live_quiz_participants_with_names(quiz_id)
        # Add each to cache
        for p in db_participants:
            student = p.get('student', {})
            name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown'
            cache.add_participant(quiz_id, p['student_id'], {
                'name': name,
                'score': p.get('score', 0),
                'current_question_index': p.get('current_question_index', 0),
                'correct_count': p.get('correct_count', 0),
                'wrong_count': p.get('wrong_count', 0),
                'skipped_count': p.get('skipped_count', 0),
                'answers': p.get('answers', {}),
                'ratings': p.get('ratings', {}),
                'status': p.get('status', 'active')
            })
        return db_participants
    else:
        # Convert cache dict to list
        result = []
        for uid, p in participants.items():
            result.append({
                'student_id': uid,
                'name': p.get('name', 'Unknown'),
                'score': p.get('score', 0),
                'current_question_index': p.get('current_question_index', 0),
                'correct_count': p.get('correct_count', 0),
                'wrong_count': p.get('wrong_count', 0),
                'skipped_count': p.get('skipped_count', 0),
                'answers': p.get('answers', {}),
                'ratings': p.get('ratings', {}),
                'status': p.get('status', 'active')
            })
        return result


# ============================================
# GENERATE JOIN CODE
# ============================================

def generate_join_code():
    """Generate a join code: 4 letters + hyphen + 4 numbers (e.g., A3B9-X7K2)"""
    letters = ''.join(secrets.choice(string.ascii_uppercase + '123456789') for _ in range(4))
    numbers = ''.join(secrets.choice('123456789') for _ in range(4))
    return f"{letters}-{numbers}"


def generate_unique_join_code():
    """Generate a unique join code"""
    code = generate_join_code()
    while True:
        quiz = get_live_quiz_by_code(code)
        if not quiz:
            return code
        code = generate_join_code()


def get_questions_for_subject(subject_id, limit):
    """Get random questions for a subject"""
    questions = get_questions_by_subject(subject_id, limit)
    available = len(questions)
    return questions, available


# ============================================
# CACHE CLEANUP THREAD (kept for performance, but not critical)
# ============================================

def start_cache_cleanup():
    """Start background thread for cache cleanup."""
    def cleanup_loop():
        while True:
            try:
                cache = get_quiz_cache()
                cache.cleanup()
                time.sleep(30)
            except Exception as e:
                print(f"Cache cleanup error: {e}")
                time.sleep(60)
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    return thread

_cleanup_thread = start_cache_cleanup()


# ============================================
# ROUTES
# ============================================

@live_quiz_bp.route('/')
def index():
    """Live quiz home"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    return render_template('dashboard/live_quiz/index.html')


@live_quiz_bp.route('/create', methods=['GET', 'POST'])
def create():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    subjects = get_all_subjects()

    if request.method == 'POST':
        subject_id = request.form.get('subject_id', '').strip()
        question_count = int(request.form.get('question_count', 10))
        title = request.form.get('title', '').strip()

        if not subject_id:
            flash('Please select a subject.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=subjects)

        questions, available = get_questions_for_subject(subject_id, question_count)

        if available == 0:
            flash('No questions available for this subject. Please select another subject.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=subjects)

        if available < question_count:
            return render_template('dashboard/live_quiz/create.html',
                                   subjects=subjects,
                                   not_enough=True,
                                   available=available,
                                   requested=question_count,
                                   subject_id=subject_id,
                                   title=title)

        join_code = generate_unique_join_code()
        question_ids = [q['id'] for q in questions]

        data = {
            'creator_id': session['user_id'],
            'title': title if title else '',
            'subject_id': subject_id,
            'question_count': question_count,
            'join_code': join_code,
            'status': 'waiting',
            'max_participants': Config.LIVE_QUIZ_MAX_PARTICIPANTS,
            'time_per_question': Config.LIVE_QUIZ_TIME_PER_QUESTION,
            'current_question_index': 0,
            'question_ids': question_ids
        }

        quiz = create_live_quiz(data)

        if quiz:
            # Get user name
            user = get_student_by_id(session['user_id'])
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant'

            # Add creator as participant
            add_live_quiz_participant(quiz['id'], session['user_id'])

            # Populate cache (optional)
            cache = get_quiz_cache()
            cache.create_quiz(quiz['id'], quiz)
            cache.add_participant(quiz['id'], session['user_id'], {
                'name': user_name,
                'score': 0,
                'current_question_index': 0,
                'correct_count': 0,
                'wrong_count': 0,
                'skipped_count': 0,
                'answers': {},
                'ratings': {},
                'status': 'active'
            })

            flash('Quiz created successfully! Share the join code.', 'success')
            return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
        else:
            flash('Failed to create quiz. Please try again.', 'error')

    return render_template('dashboard/live_quiz/create.html', subjects=subjects)


@live_quiz_bp.route('/create-with-available', methods=['POST'])
def create_with_available():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    subject_id = request.form.get('subject_id', '').strip()
    question_count = int(request.form.get('question_count', 10))
    title = request.form.get('title', '').strip()

    questions, available = get_questions_for_subject(subject_id, question_count)

    if available == 0:
        flash('No questions available.', 'error')
        return redirect(url_for('live_quiz.create'))

    join_code = generate_unique_join_code()
    question_ids = [q['id'] for q in questions]

    data = {
        'creator_id': session['user_id'],
        'title': title if title else '',
        'subject_id': subject_id,
        'question_count': available,
        'join_code': join_code,
        'status': 'waiting',
        'max_participants': Config.LIVE_QUIZ_MAX_PARTICIPANTS,
        'time_per_question': Config.LIVE_QUIZ_TIME_PER_QUESTION,
        'current_question_index': 0,
        'question_ids': question_ids
    }

    quiz = create_live_quiz(data)

    if quiz:
        user = get_student_by_id(session['user_id'])
        user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant'

        add_live_quiz_participant(quiz['id'], session['user_id'])

        cache = get_quiz_cache()
        cache.create_quiz(quiz['id'], quiz)
        cache.add_participant(quiz['id'], session['user_id'], {
            'name': user_name,
            'score': 0,
            'current_question_index': 0,
            'correct_count': 0,
            'wrong_count': 0,
            'skipped_count': 0,
            'answers': {},
            'ratings': {},
            'status': 'active'
        })

        flash(f'Quiz created with {available} questions!', 'success')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
    else:
        flash('Failed to create quiz.', 'error')

    return redirect(url_for('live_quiz.create'))


@live_quiz_bp.route('/join', methods=['GET', 'POST'])
def join():
    """Join a live quiz via join code — IDEMPOTENT"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        join_code = request.form.get('join_code', '').strip().upper()
        if not join_code:
            flash('Please enter a join code.', 'error')
            return render_template('dashboard/live_quiz/join.html')

        join_code = join_code.replace(' ', '')

        # Check if quiz exists and is waiting
        quiz = get_active_live_quiz(join_code)
        if not quiz:
            flash('Invalid join code or quiz has already started.', 'error')
            return render_template('dashboard/live_quiz/join.html')

        # Check if user already joined (idempotent)
        participant = get_live_quiz_participant(quiz['id'], session['user_id'])
        if participant:
            flash('You have already joined this quiz.', 'info')
            return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))

        # Check max participants
        participant_count = get_live_quiz_count(quiz['id'])
        if participant_count >= quiz.get('max_participants', 50):
            flash('This quiz is full.', 'error')
            return render_template('dashboard/live_quiz/join.html')

        # Get user name
        user = get_student_by_id(session['user_id'])
        user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or 'Participant'

        # Join the quiz (DB insert)
        add_live_quiz_participant(quiz['id'], session['user_id'])

        # Update cache
        cache = get_quiz_cache()
        cache.add_participant(quiz['id'], session['user_id'], {
            'name': user_name,
            'score': 0,
            'current_question_index': 0,
            'correct_count': 0,
            'wrong_count': 0,
            'skipped_count': 0,
            'answers': {},
            'ratings': {},
            'status': 'active'
        })

        # Notify creator
        notify_participant_joined(
            quiz['id'],
            quiz.get('title', 'Live Quiz'),
            user_name,
            quiz['creator_id']
        )

        flash('You have joined the quiz!', 'success')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))

    return render_template('dashboard/live_quiz/join.html')


@live_quiz_bp.route('/waiting-room/<quiz_id>')
def waiting_room(quiz_id):
    """Waiting room — safe to refresh"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    # Always load from DB to ensure consistency
    quiz = get_live_quiz_with_subject(quiz_id)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.index'))

    # Check if user is participant or creator
    participant = get_live_quiz_participant(quiz_id, session['user_id'])
    if not participant and quiz['creator_id'] != session['user_id']:
        flash('You are not a participant in this quiz.', 'error')
        return redirect(url_for('live_quiz.index'))

    is_creator = quiz['creator_id'] == session['user_id']

    # Get participants from DB
    participants_data = get_live_quiz_participants(quiz_id)
    formatted_participants = []
    for p in participants_data:
        student = p.get('student', {})
        formatted_participants.append({
            'id': p['id'],
            'student_id': p['student_id'],
            'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown',
            'public_id': student.get('public_id', '----'),
            'status': p.get('status', 'active'),
            'is_creator': p['student_id'] == quiz['creator_id']
        })

    return render_template('dashboard/live_quiz/waiting_room.html',
                         quiz=quiz,
                         is_creator=is_creator,
                         participants=formatted_participants,
                         participant_count=len(formatted_participants))


@live_quiz_bp.route('/start/<quiz_id>', methods=['POST'])
def start_quiz(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404

    if quiz['creator_id'] != session['user_id']:
        return jsonify({'error': 'Only the creator can start the quiz'}), 403

    if quiz['status'] != 'waiting':
        return jsonify({'error': 'Quiz already started or finished'}), 400

    participant_count = get_live_quiz_count(quiz_id)
    if participant_count < 2:
        return jsonify({'error': 'Need at least 2 participants to start'}), 400

    # Update DB
    update_live_quiz(quiz_id, {
        'status': 'active',
        'started_at': get_somali_time_db()
    })

    # Update cache
    cache = get_quiz_cache()
    cache.update_quiz(quiz_id, {
        'status': 'active',
        'started_at': get_somali_time_db()
    })

    # Reset participants' state
    participants = get_live_quiz_participants(quiz_id)
    for p in participants:
        student = get_student_by_id(p['student_id'])
        name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Participant' if student else 'Participant'

        update_live_quiz_participant(p['id'], {
            'current_question_index': 0,
            'score': 0,
            'correct_count': 0,
            'wrong_count': 0,
            'skipped_count': 0,
            'answers': {},
            'ratings': {}
        })
        # Update cache
        cache.update_participant(quiz_id, p['student_id'], {
            'name': name,
            'current_question_index': 0,
            'score': 0,
            'correct_count': 0,
            'wrong_count': 0,
            'skipped_count': 0,
            'answers': {},
            'ratings': {}
        })

    # Notify participants
    notify_live_quiz_start(quiz_id, quiz.get('title', 'Live Quiz'), participants)

    return jsonify({'success': True, 'quiz_id': quiz_id})


@live_quiz_bp.route('/get-question/<quiz_id>')
def get_question(quiz_id):
    """Get current question for the user — uses safe DB read"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    try:
        # Load quiz from DB (or cache if available)
        quiz = get_quiz_safe(quiz_id)
        if not quiz:
            return jsonify({'error': 'Quiz not found'}), 404

        if quiz.get('status') == 'finished':
            return jsonify({'completed': True, 'status': 'finished'})

        if quiz.get('status') != 'active':
            return jsonify({'waiting': True, 'status': quiz.get('status')})

        # Get participant (DB first, cache optional)
        participant = get_participant_safe(quiz_id, session['user_id'])
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404

        current_index = participant.get('current_question_index', 0)
        total_questions = quiz.get('question_count', 0)

        if current_index >= total_questions:
            return jsonify({'completed': True})

        question_ids = quiz.get('question_ids', [])
        if current_index >= len(question_ids):
            return jsonify({'completed': True})

        question_id = question_ids[current_index]

        # Check if already answered (for refresh recovery)
        answers = participant.get('answers', {})
        if str(question_id) in answers:
            answer_data = answers[str(question_id)]
            is_correct = answer_data.get('correct', False)
            question = get_question_by_id(question_id)
            if question:
                return jsonify({
                    'question': question,
                    'index': current_index,
                    'total': total_questions,
                    'already_answered': True,
                    'answer': answer_data.get('answer'),
                    'correct': is_correct,
                    'correct_answer': question.get('correct_answer'),
                    'explanation': question.get('explanation', '')
                })
            else:
                # Question missing, skip it and advance in DB
                new_index = current_index + 1
                update_participant_safe(quiz_id, session['user_id'], {
                    'current_question_index': new_index
                })
                return jsonify({'skipped': True})

        # Check if already rated (skip to next if so)
        ratings = participant.get('ratings', {})
        if str(question_id) in ratings:
            new_index = current_index + 1
            update_participant_safe(quiz_id, session['user_id'], {
                'current_question_index': new_index
            })
            return jsonify({'skipped': True})

        question = get_question_by_id(question_id)
        if not question:
            return jsonify({'error': 'Question not found'}), 404

        return jsonify({
            'question': question,
            'index': current_index,
            'total': total_questions,
            'already_answered': False
        })

    except Exception as e:
        # Log and return safe error
        import traceback
        print(f"Error in get_question: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Failed to load question'}), 500


@live_quiz_bp.route('/submit-answer', methods=['POST'])
def submit_answer():
    """Submit an answer — synchronously updates SQLite and cache"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')
    answer = data.get('answer')

    if not quiz_id or not question_id or not answer:
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        question = get_question_by_id(question_id)
        if not question:
            return jsonify({'error': 'Question not found'}), 404

        is_correct = answer == question['correct_answer']

        # Get participant from DB first, then update synchronously
        participant = get_live_quiz_participant(quiz_id, session['user_id'])
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404

        # Prepare updates
        answers = participant.get('answers', {})
        answers[str(question_id)] = {
            'answer': answer,
            'correct': is_correct
        }

        score = participant.get('score', 0)
        correct_count = participant.get('correct_count', 0)
        wrong_count = participant.get('wrong_count', 0)

        if is_correct:
            score += 2
            correct_count += 1
        else:
            wrong_count += 1

        updates = {
            'answers': answers,
            'score': score,
            'correct_count': correct_count,
            'wrong_count': wrong_count
        }

        # Update DB immediately
        update_live_quiz_participant(participant['id'], updates)

        # Update cache
        cache = get_quiz_cache()
        cache.update_participant(quiz_id, session['user_id'], updates)

        return jsonify({
            'correct': is_correct,
            'correct_answer': question['correct_answer'],
            'explanation': question.get('explanation', '')
        })

    except Exception as e:
        import traceback
        print(f"Error in submit_answer: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Failed to submit answer'}), 500


@live_quiz_bp.route('/skip-question', methods=['POST'])
def skip_question():
    """Skip a question — synchronously updates DB"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')

    if not quiz_id or not question_id:
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        participant = get_live_quiz_participant(quiz_id, session['user_id'])
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404

        answers = participant.get('answers', {})
        if str(question_id) in answers:
            return jsonify({'error': 'Already answered this question'}), 400

        answers[str(question_id)] = {
            'answer': None,
            'correct': False,
            'skipped': True
        }

        skipped_count = participant.get('skipped_count', 0) + 1
        current_index = participant.get('current_question_index', 0)
        new_index = current_index + 1

        updates = {
            'answers': answers,
            'skipped_count': skipped_count,
            'current_question_index': new_index
        }

        # Update DB
        update_live_quiz_participant(participant['id'], updates)

        # Update cache
        cache = get_quiz_cache()
        cache.update_participant(quiz_id, session['user_id'], updates)

        return jsonify({'success': True})

    except Exception as e:
        import traceback
        print(f"Error in skip_question: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Failed to skip question'}), 500


@live_quiz_bp.route('/submit-rating', methods=['POST'])
def submit_rating():
    """Submit rating and advance to next question — synchronous"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')
    rating = data.get('rating')

    if not quiz_id or not question_id or not rating:
        return jsonify({'error': 'Missing required fields'}), 400

    if rating not in ['HAA', 'MAY']:
        return jsonify({'error': 'Invalid rating'}), 400

    try:
        participant = get_live_quiz_participant(quiz_id, session['user_id'])
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404

        ratings = participant.get('ratings', {})
        ratings[str(question_id)] = rating

        current_index = participant.get('current_question_index', 0)
        new_index = current_index + 1

        updates = {
            'ratings': ratings,
            'current_question_index': new_index
        }

        # Update DB
        update_live_quiz_participant(participant['id'], updates)

        # Update cache
        cache = get_quiz_cache()
        cache.update_participant(quiz_id, session['user_id'], updates)

        # Check if this was the last question
        quiz = get_quiz_safe(quiz_id)
        total_questions = quiz.get('question_count', 0) if quiz else 0

        return jsonify({
            'success': True,
            'completed': new_index >= total_questions
        })

    except Exception as e:
        import traceback
        print(f"Error in submit_rating: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Failed to submit rating'}), 500


@live_quiz_bp.route('/leaderboard/<quiz_id>')
def get_leaderboard(quiz_id):
    """Get live leaderboard — uses safe participant loading"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    try:
        # Use safe function to load all participants
        participants = get_all_participants_safe(quiz_id)
        if not participants:
            return jsonify({'leaderboard': [], 'user_rank': None})

        # Sort by score descending
        sorted_p = sorted(participants, key=lambda x: x.get('score', 0), reverse=True)

        leaderboard = []
        user_rank = None
        for i, p in enumerate(sorted_p, 1):
            leaderboard.append({
                'student_id': p.get('student_id'),
                'name': p.get('name', 'Unknown'),
                'score': p.get('score', 0),
                'rank': i
            })
            if p.get('student_id') == session['user_id']:
                user_rank = i

        # Return top 5
        return jsonify({
            'leaderboard': leaderboard[:5],
            'user_rank': user_rank
        })

    except Exception as e:
        import traceback
        print(f"Error in leaderboard: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Failed to load leaderboard'}), 500


@live_quiz_bp.route('/play/<quiz_id>')
def play(quiz_id):
    """Play page — restored from DB if refreshed"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    # Load quiz from DB
    quiz = get_live_quiz_with_subject(quiz_id)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.index'))

    # Check if user is participant (DB check)
    participant = get_live_quiz_participant(quiz_id, session['user_id'])
    if not participant:
        flash('You are not a participant in this quiz.', 'error')
        return redirect(url_for('live_quiz.index'))

    return render_template('dashboard/live_quiz/play.html', quiz=quiz)


@live_quiz_bp.route('/results/<quiz_id>')
def results(quiz_id):
    """View quiz results — forces DB flush and uses DB for accuracy"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    # Force flush any pending writes (optional, but safe)
    cache = get_quiz_cache()
    cache.force_flush()

    # Load from DB
    quiz = get_live_quiz_with_subject(quiz_id)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.index'))

    is_creator = quiz['creator_id'] == session['user_id']

    # Get all participants from DB with scores
    all_participants = get_live_quiz_participants_with_names(quiz_id)

    # Get user's participant data
    user_participant = None
    for p in all_participants:
        if p['student_id'] == session['user_id']:
            user_participant = p
            break

    # Update rankings
    sorted_participants = sorted(all_participants, key=lambda x: x.get('score', 0), reverse=True)
    for i, p in enumerate(sorted_participants, 1):
        update_live_quiz_participant(p['id'], {'ranking': i})
        p['ranking'] = i

    # Check if quiz should be marked finished
    if quiz.get('status') != 'finished':
        all_completed = True
        total_questions = quiz.get('question_count', 0)
        for p in sorted_participants:
            if p.get('current_question_index', 0) < total_questions:
                all_completed = False
                break
        if all_completed and len(sorted_participants) > 0:
            update_live_quiz(quiz_id, {
                'status': 'finished',
                'ended_at': get_somali_time_db()
            })
            cache.update_quiz(quiz_id, {'status': 'finished'})
            notify_live_quiz_results(quiz_id, quiz.get('title', 'Live Quiz'), sorted_participants)

    return render_template('dashboard/live_quiz/results.html',
                         quiz=quiz,
                         is_creator=is_creator,
                         participants=sorted_participants,
                         user_participant=user_participant)


@live_quiz_bp.route('/quiz-state/<quiz_id>')
def quiz_state(quiz_id):
    """Get current quiz state — uses DB and cache for performance"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    try:
        # Load quiz from DB (or cache)
        quiz = get_quiz_safe(quiz_id)
        if not quiz:
            return jsonify({'error': 'Quiz not found'}), 404

        # Get participant from DB (or cache)
        participant = get_participant_safe(quiz_id, session['user_id'])
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404

        total_questions = quiz.get('question_count', 0)
        time_per_question = quiz.get('time_per_question', Config.LIVE_QUIZ_TIME_PER_QUESTION)
        rating_time = Config.RATING_TIME
        total_duration = total_questions * (time_per_question + rating_time)

        # Calculate remaining time (based on start time)
        started_at = quiz.get('started_at')
        remaining = total_duration
        if started_at:
            try:
                if isinstance(started_at, str):
                    started = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                else:
                    started = started_at
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                remaining = max(0, total_duration - elapsed)
            except Exception:
                remaining = total_duration

        if remaining <= 0 and quiz.get('status') == 'active':
            # Auto-finish quiz
            update_live_quiz(quiz_id, {
                'status': 'finished',
                'ended_at': get_somali_time_db()
            })
            cache.update_quiz(quiz_id, {'status': 'finished'})
            return jsonify({'status': 'finished', 'remaining_time': 0})

        current_index = participant.get('current_question_index', 0)
        is_completed = current_index >= total_questions

        # Get participant count
        participant_count = get_live_quiz_count(quiz_id)

        # Get completed count
        completed_count = 0
        all_participants = get_all_participants_safe(quiz_id)
        for p in all_participants:
            if p.get('current_question_index', 0) >= total_questions:
                completed_count += 1

        all_completed = completed_count == participant_count and participant_count > 0

        # Check if current question was answered (for reconnection)
        current_question_answered = False
        current_question_answer = None
        current_question_correct = False
        question_ids = quiz.get('question_ids', [])
        if current_index < len(question_ids):
            qid = question_ids[current_index]
            answers = participant.get('answers', {})
            if str(qid) in answers:
                current_question_answered = True
                current_question_answer = answers[str(qid)].get('answer')
                current_question_correct = answers[str(qid)].get('correct', False)

        return jsonify({
            'status': quiz.get('status'),
            'total_duration': total_duration,
            'remaining_time': int(remaining),
            'completed_count': completed_count,
            'total_participants': participant_count,
            'is_completed': is_completed,
            'current_question_index': current_index,
            'total_questions': total_questions,
            'all_completed': all_completed,
            'current_question_answered': current_question_answered,
            'current_question_answer': current_question_answer,
            'current_question_correct': current_question_correct,
            'score': participant.get('score', 0)
        })

    except Exception as e:
        import traceback
        print(f"Error in quiz_state: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Failed to get quiz state'}), 500


# ============================================
# OTHER ROUTES (analysis, export, admin endpoints)
# ============================================

@live_quiz_bp.route('/analysis/<quiz_id>')
def analysis(quiz_id):
    """Question analysis for creator"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404

    if quiz['creator_id'] != session['user_id']:
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
        analysis_data.append({
            'index': i,
            'text': q_text,
            'correct_rate': correct_rate,
            'wrong_rate': wrong_rate,
            'total_answers': total_count
        })

    most_correct = sorted(analysis_data, key=lambda x: x['correct_rate'], reverse=True)[:3]
    most_wrong = sorted(analysis_data, key=lambda x: x['wrong_rate'], reverse=True)[:3]

    return jsonify({
        'most_correct': most_correct,
        'most_wrong': most_wrong
    })


@live_quiz_bp.route('/export/<quiz_id>')
def export_results(quiz_id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    quiz = get_live_quiz_by_id(quiz_id)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.index'))

    if quiz['creator_id'] != session['user_id']:
        flash('Only the creator can export results.', 'error')
        return redirect(url_for('live_quiz.index'))

    cache = get_quiz_cache()
    cache.force_flush()

    participants = get_live_quiz_participants_with_names(quiz_id)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Rank', 'Name', 'Public ID', 'Score', 'Correct', 'Wrong', 'Skipped', 'Status'])

    sorted_participants = sorted(participants, key=lambda x: x.get('score', 0), reverse=True)
    for i, p in enumerate(sorted_participants, 1):
        student = p.get('student', {})
        name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown'
        writer.writerow([
            i,
            name,
            student.get('public_id', '----'),
            p.get('score', 0),
            p.get('correct_count', 0),
            p.get('wrong_count', 0),
            p.get('skipped_count', 0),
            p.get('status', 'active')
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=quiz_{quiz_id}_results.csv'
        }
    )


# ============================================
# ADMIN ENDPOINTS (cache management)
# ============================================

@live_quiz_bp.route('/flush-cache', methods=['POST'])
def flush_cache_endpoint():
    if 'user_id' not in session or not is_admin(session['user_id']):
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        flush_cache()
        return jsonify({'success': True, 'message': 'Cache flushed'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/cache-stats')
def cache_stats():
    if 'user_id' not in session or not is_admin(session['user_id']):
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        cache = get_quiz_cache()
        stats = cache.get_cache_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/cleanup-cache', methods=['POST'])
def cleanup_cache_endpoint():
    if 'user_id' not in session or not is_admin(session['user_id']):
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        cleanup_cache()
        return jsonify({'success': True, 'message': 'Cache cleanup done'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500