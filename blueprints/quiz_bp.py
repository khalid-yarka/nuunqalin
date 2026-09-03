from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from db import (
    get_questions_by_subject, save_quiz_attempt,
    get_user_quiz_history, update_student_points, get_student_by_id,
    get_leaderboard, get_user_subject_list
)
from utils import validate_csrf
from tier_service import (
    get_quiz_questions_limit,
    get_remaining_quota,
    check_and_consume_quota,
    get_answer_review_level,
    get_explanation_level,
    get_current_user_tier,
    has_feature,
)
from services.achievement_service import check_and_award_achievements

quiz_bp = Blueprint('quiz', __name__, url_prefix='/quiz')

@quiz_bp.route('/')
def index():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    subjects = get_user_subject_list(user_id)
    
    # Show remaining attempts
    remaining = get_remaining_quota(user_id, 'quiz_attempt')
    tier = get_current_user_tier()
    
    return render_template('dashboard/quiz/select.html', 
                           subjects=subjects,
                           remaining_attempts=remaining,
                           tier=tier)

@quiz_bp.route('/start/<subject_code>')
def start_quiz(subject_code):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user_subjects = get_user_subject_list(user_id)
    if subject_code not in [s['code'] for s in user_subjects]:
        flash('Subject not available for your location/curriculum.', 'error')
        return redirect(url_for('quiz.index'))
    
    # Check attempt quota
    remaining = get_remaining_quota(user_id, 'quiz_attempt')
    if remaining <= 0:
        flash('You have used all your quiz attempts for today. Come back tomorrow!', 'error')
        return redirect(url_for('quiz.index'))
    
    # Get the max questions allowed per quiz
    max_questions = get_quiz_questions_limit(user_id)
    questions = get_questions_by_subject(subject_code, max_questions)
    if not questions:
        flash('No questions available for this subject yet.', 'error')
        return redirect(url_for('quiz.index'))
    
    # Store in session
    session['quiz_questions'] = questions
    session['quiz_current'] = 0
    session['quiz_score'] = 0
    session['quiz_answers'] = []
    session['quiz_ratings'] = []
    session['quiz_subject_code'] = subject_code
    session['quiz_attempt_consumed'] = False
    
    # Consume the attempt atomically now
    if not check_and_consume_quota(user_id, 'quiz_attempt'):
        flash('Failed to start quiz. Try again.', 'error')
        return redirect(url_for('quiz.index'))
    
    session['quiz_attempt_consumed'] = True
    
    return redirect(url_for('quiz.play'))

@quiz_bp.route('/play')
def play():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    questions = session.get('quiz_questions', [])
    current = session.get('quiz_current', 0)
    
    if not questions:
        flash('No quiz in progress. Start a new quiz.', 'error')
        return redirect(url_for('quiz.index'))
    
    if current >= len(questions):
        return redirect(url_for('quiz.results'))
    
    question = questions[current]
    total = len(questions)
    
    # Get tier levels for UI
    review_level = get_answer_review_level(session['user_id'])
    explanation_level = get_explanation_level(session['user_id'])
    
    return render_template('dashboard/quiz/play.html', 
                         question=question, 
                         current=current, 
                         total=total,
                         review_level=review_level,
                         explanation_level=explanation_level)

@quiz_bp.route('/submit_answer', methods=['POST'])
def submit_answer():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    if not validate_csrf():
        return jsonify({'error': 'CSRF token missing or invalid'}), 403
    
    questions = session.get('quiz_questions', [])
    current = session.get('quiz_current', 0)
    
    if not questions or current >= len(questions):
        return jsonify({'error': 'Quiz not found'}), 404
    
    answer = request.json.get('answer', '')
    question = questions[current]
    
    is_correct = answer == question['correct_answer']
    
    answers = session.get('quiz_answers', [])
    answers.append({
        'question_id': question['id'],
        'answer': answer,
        'correct': is_correct
    })
    session['quiz_answers'] = answers
    
    if is_correct:
        score = session.get('quiz_score', 0) + 1
        session['quiz_score'] = score
    
    # Determine response based on tier levels
    user_id = session['user_id']
    review_level = get_answer_review_level(user_id)
    explanation_level = get_explanation_level(user_id)
    
    response = {
        'correct': is_correct,
        'correct_answer': question['correct_answer'],
        'current': current,
        'total': len(questions)
    }
    
    if review_level > 0:
        # Show correct/incorrect feedback
        response['feedback'] = is_correct
    else:
        # For Danbe, no answer review at all
        response['feedback'] = None
    
    if explanation_level > 0:
        response['explanation'] = question.get('explanation', '')
        if explanation_level > 1:
            # Extra insight: could be a related topic, but we don't have that data.
            # We'll add a placeholder or skip.
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
    
    questions = session.get('quiz_questions', [])
    current = session.get('quiz_current', 0)
    
    if not questions or current >= len(questions):
        return jsonify({'error': 'Quiz not found'}), 404
    
    rating = request.json.get('rating', '')
    
    ratings = session.get('quiz_ratings', [])
    ratings.append({
        'question_id': questions[current]['id'],
        'rating': rating
    })
    session['quiz_ratings'] = ratings
    
    session['quiz_current'] = current + 1
    
    if session['quiz_current'] >= len(questions):
        # Quiz complete – award achievements
        user_id = session['user_id']
        score = session.get('quiz_score', 0)
        total = len(questions)
        # Check for achievements
        check_and_award_achievements(user_id, 'quiz_completed', {'score': score, 'total': total})
        return jsonify({'complete': True})
    
    return jsonify({'complete': False, 'next': session['quiz_current']})

@quiz_bp.route('/results')
def results():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    questions = session.get('quiz_questions', [])
    answers = session.get('quiz_answers', [])
    score = session.get('quiz_score', 0)
    total = len(questions)
    subject_code = session.get('quiz_subject_code')
    
    if not questions:
        flash('No quiz completed.', 'error')
        return redirect(url_for('quiz.index'))
    
    if subject_code:
        save_quiz_attempt(
            session['user_id'],
            subject_code,
            score,
            total,
            answers,
            session.get('quiz_ratings', [])
        )
        
        student = get_student_by_id(session['user_id'])
        if student:
            current_points = student.get('total_points', 0)
            new_points = current_points + score
            update_student_points(session['user_id'], new_points)
    
    # Attempt was already consumed at start, so no need to consume again.
    # But we should ensure we don't consume twice.
    
    session.pop('quiz_questions', None)
    session.pop('quiz_current', None)
    session.pop('quiz_score', None)
    session.pop('quiz_answers', None)
    session.pop('quiz_ratings', None)
    session.pop('quiz_subject_code', None)
    session.pop('quiz_attempt_consumed', None)
    
    return render_template('dashboard/quiz/results.html', 
                         score=score, 
                         total=total, 
                         percentage=round((score/total)*100) if total > 0 else 0)

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
    
    # Get tier level for detailed ranking stats
    level = get_feature_level("detailed_ranking_stats", session['user_id'])
    
    return render_template('dashboard/quiz/leaderboard.html', 
                         leaders=leaders, 
                         user_rank=user_rank,
                         ranking_level=level)