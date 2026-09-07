from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from db import (
    get_questions_by_subject, save_quiz_attempt,
    get_user_quiz_history, update_student_points, get_student_by_id,
    get_leaderboard, get_user_subject_list
)
from utils import validate_csrf
from services.tier_service import (
    get_quiz_questions_limit,
    get_remaining_quota,
    check_and_consume_quota,
    get_answer_review_level,
    get_explanation_level,
    get_current_user_tier,
    get_feature_level,
    get_user_tier,
    get_allowed_question_counts,
    validate_question_count,
    is_custom_question_count_allowed
)
from services.achievement_service import check_and_award_achievements
from user_settings import get_user_settings
import json

quiz_bp = Blueprint('quiz', __name__, url_prefix='/quiz')


@quiz_bp.route('/')
def index():
    """Unified setup page: choose subject and question count."""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    # Check if user has an active quiz session
    quiz_data = session.get('quiz')
    if quiz_data and quiz_data.get('questions'):
        # User has a quiz in progress – redirect to play
        flash('Resuming your quiz...', 'info')
        return redirect(url_for('quiz.play'))

    user_id = session['user_id']
    subjects = get_user_subject_list(user_id)
    if not subjects:
        flash('Please set your location and curriculum in your profile to access quizzes.', 'error')
        return redirect(url_for('dashboard.profile'))

    # Get allowed counts for this user
    allowed_counts = get_allowed_question_counts(user_id)
    tier = get_current_user_tier()
    remaining_attempts = get_remaining_quota(user_id, 'quiz_attempt')

    return render_template('dashboard/quiz/setup.html',
                           subjects=subjects,
                           allowed_counts=allowed_counts,
                           tier=tier,
                           remaining_attempts=remaining_attempts,
                           is_custom_allowed=is_custom_question_count_allowed(user_id))


@quiz_bp.route('/start', methods=['POST'])
def start_quiz():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    if not validate_csrf():
        flash('Invalid CSRF token. Please try again.', 'error')
        return redirect(url_for('quiz.index'))

    user_id = session['user_id']
    subject_code = request.form.get('subject_code', '').strip()
    question_count_str = request.form.get('question_count', '').strip()
    custom_count_str = request.form.get('custom_count', '').strip()

    # Validate subject
    user_subjects = get_user_subject_list(user_id)
    if subject_code not in [s['code'] for s in user_subjects]:
        flash('Invalid subject selected.', 'error')
        return redirect(url_for('quiz.index'))

    # Determine final question count
    if question_count_str == 'custom' and custom_count_str:
        try:
            question_count = int(custom_count_str)
        except ValueError:
            flash('Please enter a valid number.', 'error')
            return redirect(url_for('quiz.index'))
    else:
        try:
            question_count = int(question_count_str)
        except ValueError:
            flash('Invalid question count.', 'error')
            return redirect(url_for('quiz.index'))

    # Validate against tier rules
    if not validate_question_count(user_id, question_count):
        flash('Question count not allowed for your tier.', 'error')
        return redirect(url_for('quiz.index'))

    # Check quota
    remaining = get_remaining_quota(user_id, 'quiz_attempt')
    if remaining <= 0:
        flash('You have used all your quiz attempts for today. Come back tomorrow!', 'error')
        return redirect(url_for('quiz.index'))

    # Fetch questions
    questions = get_questions_by_subject(subject_code, question_count)
    if not questions:
        flash('No questions available for this subject yet.', 'error')
        return redirect(url_for('quiz.index'))

    # Consume one attempt
    if not check_and_consume_quota(user_id, 'quiz_attempt'):
        flash('Failed to start quiz. Try again.', 'error')
        return redirect(url_for('quiz.index'))

    # Initialise session quiz data
    session['quiz'] = {
        'subject_code': subject_code,
        'question_count': len(questions),
        'questions': questions,
        'current_index': 0,
        'score': 0,
        'answers': [],
        'ratings': [],
        'reactions': {
            'likes': [],
            'saves': [],
            'reports': {}
        }
    }

    return redirect(url_for('quiz.play'))


@quiz_bp.route('/play')
def play():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    quiz_data = session.get('quiz')
    if not quiz_data or not quiz_data.get('questions'):
        flash('No quiz in progress. Start a new quiz.', 'error')
        return redirect(url_for('quiz.index'))

    questions = quiz_data['questions']
    current_index = quiz_data['current_index']
    if current_index >= len(questions):
        return redirect(url_for('quiz.results'))

    question = questions[current_index]
    total = len(questions)
    score = quiz_data['score']

    user_settings = get_user_settings(session['user_id'])
    user_tier = get_user_tier(session['user_id'])

    return render_template('dashboard/quiz/play.html',
                           question=question,
                           current=current_index,
                           total=total,
                           score=score,
                           user_settings=user_settings,
                           user_tier=user_tier)


@quiz_bp.route('/submit_answer', methods=['POST'])
def submit_answer():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403

    quiz_data = session.get('quiz')
    if not quiz_data:
        return jsonify({'error': 'No quiz in progress'}), 400

    questions = quiz_data['questions']
    current_index = quiz_data['current_index']
    if current_index >= len(questions):
        return jsonify({'error': 'Quiz already completed'}), 400

    answer = request.json.get('answer', '')
    question = questions[current_index]
    is_correct = answer == question['correct_answer']

    # Append answer to session
    answers = quiz_data['answers']
    answers.append({
        'question_id': question['id'],
        'answer': answer,
        'correct': is_correct
    })
    quiz_data['answers'] = answers

    if is_correct:
        quiz_data['score'] += 1

    session['quiz'] = quiz_data
    session.modified = True

    user_id = session['user_id']
    review_level = get_answer_review_level(user_id)
    explanation_level = get_explanation_level(user_id)

    response = {
        'correct': is_correct,
        'correct_answer': question['correct_answer'],
        'current': current_index,
        'total': len(questions),
        'score': quiz_data['score']
    }

    if review_level > 0:
        response['feedback'] = is_correct
    else:
        response['feedback'] = None

    if explanation_level > 0:
        response['explanation'] = question.get('explanation', '')
        if explanation_level > 1:
            response['extra_insight'] = None
    else:
        response['explanation'] = None

    return jsonify(response)


@quiz_bp.route('/submit_rating', methods=['POST'])
def submit_rating():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403

    quiz_data = session.get('quiz')
    if not quiz_data:
        return jsonify({'error': 'No quiz in progress'}), 400

    questions = quiz_data['questions']
    current_index = quiz_data['current_index']
    if current_index >= len(questions):
        return jsonify({'error': 'Quiz already completed'}), 400

    rating = request.json.get('rating', '')
    ratings = quiz_data['ratings']
    ratings.append({
        'question_id': questions[current_index]['id'],
        'rating': rating
    })
    quiz_data['ratings'] = ratings
    quiz_data['current_index'] += 1
    session['quiz'] = quiz_data
    session.modified = True

    if quiz_data['current_index'] >= len(questions):
        user_id = session['user_id']
        score = quiz_data['score']
        total = len(questions)
        check_and_award_achievements(user_id, 'quiz_completed', {'score': score, 'total': total})
        return jsonify({'complete': True})

    return jsonify({'complete': False, 'next': quiz_data['current_index']})


@quiz_bp.route('/skip_rating', methods=['POST'])
def skip_rating():
    """Skip rating and advance to next question."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403

    quiz_data = session.get('quiz')
    if not quiz_data:
        return jsonify({'error': 'No quiz in progress'}), 400

    questions = quiz_data['questions']
    current_index = quiz_data['current_index']
    if current_index >= len(questions):
        return jsonify({'error': 'Quiz already completed'}), 400

    # Advance to next question without rating
    quiz_data['current_index'] += 1
    session['quiz'] = quiz_data
    session.modified = True

    if quiz_data['current_index'] >= len(questions):
        user_id = session['user_id']
        score = quiz_data['score']
        total = len(questions)
        check_and_award_achievements(user_id, 'quiz_completed', {'score': score, 'total': total})
        return jsonify({'complete': True})

    return jsonify({'complete': False, 'next': quiz_data['current_index']})


@quiz_bp.route('/results')
def results():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    quiz_data = session.pop('quiz', None)
    if not quiz_data or not quiz_data.get('questions'):
        flash('No quiz completed.', 'error')
        return redirect(url_for('quiz.index'))

    questions = quiz_data['questions']
    answers = quiz_data['answers']
    score = quiz_data['score']
    total = len(questions)
    subject_code = quiz_data['subject_code']
    ratings = quiz_data['ratings']
    reactions = quiz_data['reactions']

    save_quiz_attempt(
        session['user_id'],
        subject_code,
        score,
        total,
        answers,
        ratings,
        reactions
    )

    student = get_student_by_id(session['user_id'])
    if student:
        current_points = student.get('total_points', 0)
        new_points = current_points + score
        update_student_points(session['user_id'], new_points)

    return render_template('dashboard/quiz/results.html',
                         score=score,
                         total=total,
                         percentage=round((score/total)*100) if total > 0 else 0,
                         answers=answers,
                         ratings=ratings,
                         reactions=reactions,
                         questions=questions)


@quiz_bp.route('/history')
def history():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    attempts = get_user_quiz_history(session['user_id'], 20)
    return render_template('dashboard/quiz/history.html', attempts=attempts)


@quiz_bp.route('/leaderboard')
def leaderboard():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    leaders = get_leaderboard(50)

    user_rank = None
    for i, student in enumerate(leaders, 1):
        if student.get('id') == session['user_id']:
            user_rank = i
            break

    level = get_feature_level("detailed_ranking_stats", session['user_id'])

    return render_template('dashboard/quiz/leaderboard.html',
                         leaders=leaders,
                         user_rank=user_rank,
                         ranking_level=level)