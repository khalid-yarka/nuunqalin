from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from supabase_client import supabase, get_all_subjects, get_questions_by_subject, save_quiz_attempt, get_user_quiz_history, update_student_points

quiz_bp = Blueprint('quiz', __name__, url_prefix='/quiz')


@quiz_bp.route('/')
def index():
    """Quiz home - select subject"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    subjects = get_all_subjects()
    return render_template('dashboard/quiz/select.html', subjects=subjects)


@quiz_bp.route('/start/<subject_id>')
def start_quiz(subject_id):
    """Start a quiz for a subject"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    # Get questions for this subject
    questions = get_questions_by_subject(subject_id, 10)
    
    if not questions:
        flash('No questions available for this subject yet.', 'error')
        return redirect(url_for('quiz.index'))
    
    # Store questions in session
    session['quiz_questions'] = questions
    session['quiz_current'] = 0
    session['quiz_score'] = 0
    session['quiz_answers'] = []
    session['quiz_ratings'] = []
    session['quiz_subject_id'] = subject_id
    
    return redirect(url_for('quiz.play'))


@quiz_bp.route('/play')
def play():
    """Play the quiz"""
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
    """Submit an answer and get feedback"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    questions = session.get('quiz_questions', [])
    current = session.get('quiz_current', 0)
    
    if not questions or current >= len(questions):
        return jsonify({'error': 'Quiz not found'}), 404
    
    answer = request.json.get('answer', '')
    question = questions[current]
    
    is_correct = answer == question['correct_answer']
    
    # Store answer
    answers = session.get('quiz_answers', [])
    answers.append({
        'question_id': question['id'],
        'answer': answer,
        'correct': is_correct
    })
    session['quiz_answers'] = answers
    
    # Update score
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
    """Submit rating for current question"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    questions = session.get('quiz_questions', [])
    current = session.get('quiz_current', 0)
    
    if not questions or current >= len(questions):
        return jsonify({'error': 'Quiz not found'}), 404
    
    rating = request.json.get('rating', '')  # 'HAA' or 'MAY'
    
    ratings = session.get('quiz_ratings', [])
    ratings.append({
        'question_id': questions[current]['id'],
        'rating': rating
    })
    session['quiz_ratings'] = ratings
    
    # Move to next question
    session['quiz_current'] = current + 1
    
    # Check if quiz is complete
    if session['quiz_current'] >= len(questions):
        return jsonify({'complete': True})
    
    return jsonify({'complete': False, 'next': session['quiz_current']})


@quiz_bp.route('/results')
def results():
    """Show quiz results"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    questions = session.get('quiz_questions', [])
    answers = session.get('quiz_answers', [])
    score = session.get('quiz_score', 0)
    total = len(questions)
    subject_id = session.get('quiz_subject_id')
    
    if not questions:
        flash('No quiz completed.', 'error')
        return redirect(url_for('quiz.index'))
    
    # Save attempt to database
    if subject_id:
        save_quiz_attempt(
            session['user_id'],
            subject_id,
            score,
            total,
            answers,
            session.get('quiz_ratings', [])
        )
        
        # Update total points
        student = supabase.table('students').select('total_points').eq('id', session['user_id']).execute()
        if student.data:
            current_points = student.data[0].get('total_points', 0)
            new_points = current_points + score
            update_student_points(session['user_id'], new_points)
    
    # Clear session quiz data
    session.pop('quiz_questions', None)
    session.pop('quiz_current', None)
    session.pop('quiz_score', None)
    session.pop('quiz_answers', None)
    session.pop('quiz_ratings', None)
    session.pop('quiz_subject_id', None)
    
    return render_template('dashboard/quiz/results.html', 
                         score=score, 
                         total=total, 
                         percentage=round((score/total)*100) if total > 0 else 0,
                         answers=answers,
                         questions=questions)


@quiz_bp.route('/history')
def history():
    """View quiz history"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    attempts = get_user_quiz_history(session['user_id'], 20)
    return render_template('dashboard/quiz/history.html', attempts=attempts)


@quiz_bp.route('/leaderboard')
def leaderboard():
    """Global leaderboard"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    try:
        response = supabase.table('students')\
            .select('public_id, first_name, last_name, total_points, school')\
            .order('total_points', desc=True)\
            .limit(50)\
            .execute()
        leaders = response.data if response.data else []
    except Exception as e:
        print(f"Error fetching leaderboard: {e}")
        leaders = []
    
    # Get user's rank
    user_rank = None
    try:
        rank_response = supabase.table('students')\
            .select('total_points')\
            .order('total_points', desc=True)\
            .execute()
        
        for i, student in enumerate(rank_response.data, 1):
            if student.get('id') == session['user_id']:
                user_rank = i
                break
    except Exception:
        pass
    
    return render_template('dashboard/quiz/leaderboard.html', 
                         leaders=leaders, 
                         user_rank=user_rank)