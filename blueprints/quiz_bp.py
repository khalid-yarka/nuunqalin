from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from db import (
    get_questions_by_subject, save_quiz_attempt,
    get_user_quiz_history, update_student_points, get_student_by_id,
    get_leaderboard, get_user_subject_list
)

quiz_bp = Blueprint('quiz', __name__, url_prefix='/quiz')

@quiz_bp.route('/')
def index():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    subjects = get_user_subject_list(user_id)   # Filtered by user's location/curriculum
    return render_template('dashboard/quiz/select.html', subjects=subjects)

@quiz_bp.route('/start/<subject_code>')
def start_quiz(subject_code):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    # Verify user can access this subject
    user_subjects = get_user_subject_list(session['user_id'])
    if subject_code not in [s['code'] for s in user_subjects]:
        flash('Subject not available for your location/curriculum.', 'error')
        return redirect(url_for('quiz.index'))
    
    questions = get_questions_by_subject(subject_code, 10)
    if not questions:
        flash('No questions available for this subject yet.', 'error')
        return redirect(url_for('quiz.index'))
    
    session['quiz_questions'] = questions
    session['quiz_current'] = 0
    session['quiz_score'] = 0
    session['quiz_answers'] = []
    session['quiz_ratings'] = []
    session['quiz_subject_code'] = subject_code
    
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
    
    return render_template('dashboard/quiz/play.html', 
                         question=question, 
                         current=current, 
                         total=total)

@quiz_bp.route('/submit_answer', methods=['POST'])
def submit_answer():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
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
    
    return jsonify({
        'correct': is_correct,
        'correct_answer': question['correct_answer'],
        'explanation': question.get('explanation', ''),
        'current': current,
        'total': len(questions)
    })

@quiz_bp.route('/submit_rating', methods=['POST'])
def submit_rating():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
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
    
    session.pop('quiz_questions', None)
    session.pop('quiz_current', None)
    session.pop('quiz_score', None)
    session.pop('quiz_answers', None)
    session.pop('quiz_ratings', None)
    session.pop('quiz_subject_code', None)
    
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
    
    return render_template('dashboard/quiz/leaderboard.html', 
                         leaders=leaders, 
                         user_rank=user_rank)