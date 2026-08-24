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
    get_live_quiz_by_id, get_questions_by_subject
)
import secrets
import string
import random
import csv
from io import StringIO
from datetime import datetime, timezone

live_quiz_bp = Blueprint('live_quiz', __name__, url_prefix='/live-quiz')


# ============================================
# HELPERS
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
    """Create a live quiz"""
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
        
        # Check if subject has enough questions
        questions, available = get_questions_for_subject(subject_id, question_count)
        
        if available == 0:
            flash('No questions available for this subject. Please select another subject.', 'error')
            return render_template('dashboard/live_quiz/create.html', subjects=subjects)
        
        # If not enough questions, handle it
        if available < question_count:
            return render_template('dashboard/live_quiz/create.html',
                                 subjects=subjects,
                                 not_enough=True,
                                 available=available,
                                 requested=question_count,
                                 subject_id=subject_id,
                                 title=title)
        
        # Generate join code
        join_code = generate_unique_join_code()
        
        # Extract just the IDs
        question_ids = [q['id'] for q in questions]
        
        # Create quiz
        data = {
            'creator_id': session['user_id'],
            'title': title if title else '',
            'subject_id': subject_id,
            'question_count': question_count,
            'join_code': join_code,
            'status': 'waiting',
            'max_participants': 50,
            'time_per_question': 30,
            'current_question_index': 0,
            'question_ids': question_ids
        }
        
        quiz = create_live_quiz(data)
        
        if quiz:
            # Add creator as a participant
            add_live_quiz_participant(quiz['id'], session['user_id'])
            
            flash('Quiz created successfully! Share the join code.', 'success')
            return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
        else:
            flash('Failed to create quiz. Please try again.', 'error')
    
    return render_template('dashboard/live_quiz/create.html', subjects=subjects)


@live_quiz_bp.route('/create-with-available', methods=['POST'])
def create_with_available():
    """Create a quiz with available questions (when not enough)"""
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
        'max_participants': 50,
        'time_per_question': 30,
        'current_question_index': 0,
        'question_ids': question_ids
    }
    
    quiz = create_live_quiz(data)
    
    if quiz:
        # Add creator as a participant
        add_live_quiz_participant(quiz['id'], session['user_id'])
        
        flash(f'Quiz created with {available} questions!', 'success')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
    else:
        flash('Failed to create quiz.', 'error')
    
    return redirect(url_for('live_quiz.create'))


@live_quiz_bp.route('/join', methods=['GET', 'POST'])
def join():
    """Join a live quiz via join code"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        join_code = request.form.get('join_code', '').strip().upper()
        
        if not join_code:
            flash('Please enter a join code.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        
        # Remove any spaces
        join_code = join_code.replace(' ', '')
        
        # Check if quiz exists and is waiting
        quiz = get_active_live_quiz(join_code)
        
        if not quiz:
            flash('Invalid join code or quiz has already started.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        
        # Check if user already joined
        participant = get_live_quiz_participant(quiz['id'], session['user_id'])
        
        if participant:
            flash('You have already joined this quiz.', 'info')
            return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
        
        # Check if max participants reached
        participant_count = get_live_quiz_count(quiz['id'])
        
        if participant_count >= quiz.get('max_participants', 50):
            flash('This quiz is full.', 'error')
            return render_template('dashboard/live_quiz/join.html')
        
        # Join the quiz
        add_live_quiz_participant(quiz['id'], session['user_id'])
        
        flash('You have joined the quiz!', 'success')
        return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
    
    return render_template('dashboard/live_quiz/join.html')


@live_quiz_bp.route('/waiting-room/<quiz_id>')
def waiting_room(quiz_id):
    """Waiting room for a quiz"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    quiz = get_live_quiz_with_subject(quiz_id)
    
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.index'))
    
    # Check if user is participant
    participant = get_live_quiz_participant(quiz_id, session['user_id'])
    
    if not participant and quiz['creator_id'] != session['user_id']:
        flash('You are not a participant in this quiz.', 'error')
        return redirect(url_for('live_quiz.index'))
    
    is_creator = quiz['creator_id'] == session['user_id']
    
    # Get all participants
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
    """Start a live quiz"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        # Get quiz
        quiz = get_live_quiz_by_id(quiz_id)
        
        if not quiz:
            return jsonify({'error': 'Quiz not found'}), 404
        
        # Check if user is creator
        if quiz['creator_id'] != session['user_id']:
            return jsonify({'error': 'Only the creator can start the quiz'}), 403
        
        # Check if already started
        if quiz['status'] != 'waiting':
            return jsonify({'error': 'Quiz already started or finished'}), 400
        
        # Get participant count
        participant_count = get_live_quiz_count(quiz_id)
        
        # Minimum 2 participants
        if participant_count < 2:
            return jsonify({'error': 'Need at least 2 participants to start'}), 400
        
        # Update quiz status
        update_live_quiz(quiz_id, {
            'status': 'active',
            'started_at': datetime.now(timezone.utc).isoformat()
        })
        
        # Get all participants to reset
        participants = get_live_quiz_participants(quiz_id)
        
        for p in participants:
            update_live_quiz_participant(p['id'], {
                'current_question_index': 0,
                'score': 0,
                'correct_count': 0,
                'wrong_count': 0,
                'skipped_count': 0,
                'answers': {},
                'ratings': {}
            })
        
        return jsonify({'success': True, 'quiz_id': quiz_id})
        
    except Exception as e:
        print(f"Error starting quiz: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/my-participant/<quiz_id>')
def my_participant(quiz_id):
    """Get current user's participant data"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    participant = get_live_quiz_participant(quiz_id, session['user_id'])
    
    if participant:
        return jsonify(participant)
    return jsonify({'error': 'Not a participant'}), 404


@live_quiz_bp.route('/get-question/<quiz_id>')
def get_question(quiz_id):
    """Get current question for the user"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        # Get quiz
        quiz = get_live_quiz_by_id(quiz_id)
        
        if not quiz:
            return jsonify({'error': 'Quiz not found'}), 404
        
        # Check if quiz is finished
        if quiz['status'] == 'finished':
            return jsonify({'completed': True, 'status': 'finished'})
        
        # If quiz is not active, return waiting status
        if quiz['status'] != 'active':
            return jsonify({'waiting': True, 'status': quiz['status']})
        
        # Get participant
        participant = get_live_quiz_participant(quiz_id, session['user_id'])
        
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404
        
        current_index = participant.get('current_question_index', 0)
        total_questions = quiz.get('question_count', 0)
        
        # Check if participant completed all questions
        if current_index >= total_questions:
            return jsonify({'completed': True})
        
        # Get the question
        question_ids = quiz.get('question_ids', [])
        if current_index >= len(question_ids):
            return jsonify({'completed': True})
        
        question_id = question_ids[current_index]
        
        # Get full question data
        question = get_question_by_id(question_id)
        
        if not question:
            return jsonify({'error': 'Question not found'}), 404
        
        return jsonify({
            'question': question,
            'index': current_index,
            'total': total_questions
        })
        
    except Exception as e:
        print(f"Error getting question: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/submit-answer', methods=['POST'])
def submit_answer():
    """Submit an answer for a question"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')
    answer = data.get('answer')
    
    if not quiz_id or not question_id or not answer:
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        # Get question
        question = get_question_by_id(question_id)
        
        if not question:
            return jsonify({'error': 'Question not found'}), 404
        
        is_correct = answer == question['correct_answer']
        
        # Get participant
        participant = get_live_quiz_participant(quiz_id, session['user_id'])
        
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404
        
        # Update participant
        answers = participant.get('answers', {})
        answers[question_id] = {
            'answer': answer,
            'correct': is_correct
        }
        
        score = participant.get('score', 0)
        correct_count = participant.get('correct_count', 0)
        wrong_count = participant.get('wrong_count', 0)
        
        if is_correct:
            score += 2  # 2 points per correct answer
            correct_count += 1
        else:
            wrong_count += 1
        
        # Save the answer but DON'T advance question yet
        update_live_quiz_participant(participant['id'], {
            'answers': answers,
            'score': score,
            'correct_count': correct_count,
            'wrong_count': wrong_count
        })
        
        return jsonify({
            'correct': is_correct,
            'correct_answer': question['correct_answer'],
            'explanation': question.get('explanation', '')
        })
        
    except Exception as e:
        print(f"Error submitting answer: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/skip-question', methods=['POST'])
def skip_question():
    """Skip a question (only if not answered)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')
    
    if not quiz_id or not question_id:
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        # Get participant
        participant = get_live_quiz_participant(quiz_id, session['user_id'])
        
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404
        
        # Check if already answered
        answers = participant.get('answers', {})
        if question_id in answers:
            return jsonify({'error': 'Already answered this question'}), 400
        
        # Update participant - skip and advance
        answers[question_id] = {
            'answer': None,
            'correct': False,
            'skipped': True
        }
        
        skipped_count = participant.get('skipped_count', 0) + 1
        current_index = participant.get('current_question_index', 0)
        new_index = current_index + 1
        
        update_live_quiz_participant(participant['id'], {
            'answers': answers,
            'skipped_count': skipped_count,
            'current_question_index': new_index
        })
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error skipping question: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/submit-rating', methods=['POST'])
def submit_rating():
    """Submit HAA/MAY rating and advance to next question"""
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
        # Get participant
        participant = get_live_quiz_participant(quiz_id, session['user_id'])
        
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404
        
        # Update ratings
        ratings = participant.get('ratings', {})
        ratings[question_id] = rating
        
        # Advance to next question
        current_index = participant.get('current_question_index', 0)
        new_index = current_index + 1
        
        update_live_quiz_participant(participant['id'], {
            'ratings': ratings,
            'current_question_index': new_index
        })
        
        # Check if this was the last question
        quiz = get_live_quiz_by_id(quiz_id)
        total_questions = quiz.get('question_count', 0) if quiz else 0
        
        return jsonify({
            'success': True,
            'completed': new_index >= total_questions
        })
        
    except Exception as e:
        print(f"Error submitting rating: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/leaderboard/<quiz_id>')
def get_leaderboard(quiz_id):
    """Get live leaderboard for a quiz"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        # Get all participants with student names
        participants = get_live_quiz_participants_with_names(quiz_id)
        
        # Format leaderboard
        leaderboard = []
        user_rank = None
        
        for i, p in enumerate(participants, 1):
            student = p.get('student', {})
            name = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() or 'Unknown'
            
            leaderboard.append({
                'student_id': p['student_id'],
                'name': name,
                'public_id': student.get('public_id', '----'),
                'score': p.get('score', 0)
            })
            
            if p['student_id'] == session['user_id']:
                user_rank = i
        
        # Get top 5
        top_5 = leaderboard[:5]
        
        return jsonify({
            'leaderboard': top_5,
            'user_rank': user_rank
        })
        
    except Exception as e:
        print(f"Error getting leaderboard: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/play/<quiz_id>')
def play(quiz_id):
    """Play a live quiz"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    quiz = get_live_quiz_with_subject(quiz_id)
    
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.index'))
    
    # Check if user is participant
    participant = get_live_quiz_participant(quiz_id, session['user_id'])
    
    if not participant:
        flash('You are not a participant in this quiz.', 'error')
        return redirect(url_for('live_quiz.index'))
    
    return render_template('dashboard/live_quiz/play.html', quiz=quiz)


@live_quiz_bp.route('/results/<quiz_id>')
def results(quiz_id):
    """View quiz results"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    quiz = get_live_quiz_with_subject(quiz_id)
    
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('live_quiz.index'))
    
    is_creator = quiz['creator_id'] == session['user_id']
    
    participant = get_live_quiz_participant(quiz_id, session['user_id'])
    
    if not participant and not is_creator:
        flash('You are not authorized to view these results.', 'error')
        return redirect(url_for('live_quiz.index'))
    
    # Get all participants with scores
    all_participants = get_live_quiz_participants_with_names(quiz_id)
    
    # Get user's participant data
    user_participant = None
    for p in all_participants:
        if p['student_id'] == session['user_id']:
            user_participant = p
            break
    
    # Update rankings
    for i, p in enumerate(all_participants, 1):
        update_live_quiz_participant(p['id'], {'ranking': i})
        p['ranking'] = i
    
    # Check if quiz should be marked as finished
    quiz_status = quiz.get('status')
    if quiz_status != 'finished':
        # Check if all participants completed
        all_completed = True
        total_questions = quiz.get('question_count', 0)
        for p in all_participants:
            if p.get('current_question_index', 0) < total_questions:
                all_completed = False
                break
        
        if all_completed and len(all_participants) > 0:
            update_live_quiz(quiz_id, {
                'status': 'finished',
                'ended_at': datetime.now(timezone.utc).isoformat()
            })
    
    return render_template('dashboard/live_quiz/results.html',
                         quiz=quiz,
                         is_creator=is_creator,
                         participants=all_participants,
                         user_participant=user_participant)


# ============================================
# QUIZ STATE (For participants to poll)
# ============================================

@live_quiz_bp.route('/quiz-state/<quiz_id>')
def quiz_state(quiz_id):
    """Get current quiz state including total timer"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        # Get quiz
        quiz = get_live_quiz_by_id(quiz_id)
        
        if not quiz:
            return jsonify({'error': 'Quiz not found'}), 404
        
        # Check if user is participant
        participant = get_live_quiz_participant(quiz_id, session['user_id'])
        
        if not participant:
            return jsonify({'error': 'Not a participant'}), 404
        
        # Calculate total timer
        total_questions = quiz.get('question_count', 0)
        time_per_question = quiz.get('time_per_question', 30)
        rating_time = 10  # 10 seconds for rating
        total_duration = total_questions * (time_per_question + rating_time)
        
        # Calculate remaining time
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
            except Exception as e:
                print(f"Error calculating time: {e}")
                remaining = total_duration
        
        # Check if timer expired
        if remaining <= 0 and quiz.get('status') == 'active':
            # End the quiz
            update_live_quiz(quiz_id, {
                'status': 'finished',
                'ended_at': datetime.now(timezone.utc).isoformat()
            })
            return jsonify({'status': 'finished', 'remaining_time': 0})
        
        # Get participant progress
        current_index = participant.get('current_question_index', 0)
        is_completed = current_index >= total_questions
        
        # Get all participants for leaderboard
        participants_data = get_live_quiz_participants_with_names(quiz_id)
        
        # Calculate completed count
        completed_count = 0
        for p in participants_data:
            if p.get('current_question_index', 0) >= total_questions:
                completed_count += 1
        
        # Check if all participants completed
        all_completed = completed_count == len(participants_data) and len(participants_data) > 0
        
        return jsonify({
            'status': quiz.get('status'),
            'total_duration': total_duration,
            'remaining_time': int(remaining),
            'completed_count': completed_count,
            'total_participants': len(participants_data),
            'is_completed': is_completed,
            'current_question_index': current_index,
            'total_questions': total_questions,
            'all_completed': all_completed
        })
        
    except Exception as e:
        print(f"Error getting quiz state: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/analysis/<quiz_id>')
def analysis(quiz_id):
    """Get question analysis (creator only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        # Check if user is creator
        quiz = get_live_quiz_by_id(quiz_id)
        
        if not quiz:
            return jsonify({'error': 'Quiz not found'}), 404
        
        if quiz['creator_id'] != session['user_id']:
            return jsonify({'error': 'Only the creator can view analysis'}), 403
        
        question_ids = quiz.get('question_ids', [])
        
        # Get all participants' answers
        participants = get_live_quiz_participants(quiz_id)
        
        # Analyze each question
        analysis_data = []
        for i, qid in enumerate(question_ids):
            correct_count = 0
            total_count = 0
            
            for p in participants:
                answers = p.get('answers', {})
                if qid in answers:
                    total_count += 1
                    if answers[qid].get('correct', False):
                        correct_count += 1
            
            # Get question text
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
        
        # Sort by correct rate
        most_correct = sorted(analysis_data, key=lambda x: x['correct_rate'], reverse=True)[:3]
        most_wrong = sorted(analysis_data, key=lambda x: x['wrong_rate'], reverse=True)[:3]
        
        return jsonify({
            'most_correct': most_correct,
            'most_wrong': most_wrong
        })
        
    except Exception as e:
        print(f"Error getting analysis: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/export/<quiz_id>')
def export_results(quiz_id):
    """Export quiz results as CSV (creator only)"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    try:
        # Check if user is creator
        quiz = get_live_quiz_by_id(quiz_id)
        
        if not quiz:
            flash('Quiz not found.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        if quiz['creator_id'] != session['user_id']:
            flash('Only the creator can export results.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        # Get all participants
        participants = get_live_quiz_participants_with_names(quiz_id)
        
        # Create CSV
        output = StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['Rank', 'Name', 'Public ID', 'Score', 'Correct', 'Wrong', 'Skipped', 'Status'])
        
        # Data
        for i, p in enumerate(participants, 1):
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
        
        # Create response
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=quiz_{quiz_id}_results.csv'
            }
        )
        
    except Exception as e:
        print(f"Error exporting results: {e}")
        flash('Error exporting results.', 'error')
        return redirect(url_for('live_quiz.results', quiz_id=quiz_id))