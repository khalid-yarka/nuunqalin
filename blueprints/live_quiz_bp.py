from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify, Response
from supabase_client import supabase, get_all_subjects
import secrets
import string
import random
import json
import csv
from io import StringIO
import datetime

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
        try:
            response = supabase.table('live_quizzes').select('id').eq('join_code', code).execute()
            if not response.data:
                return code
            code = generate_join_code()
        except Exception:
            return code


def get_questions_for_subject(subject_id, limit):
    """Get random questions for a subject"""
    try:
        response = supabase.table('questions')\
            .select('id, question_text, options, correct_answer, explanation')\
            .eq('subject_id', subject_id)\
            .execute()
        
        questions = response.data if response.data else []
        if len(questions) < limit:
            return questions, len(questions)
        
        selected = random.sample(questions, limit)
        return selected, limit
    except Exception as e:
        print(f"Error fetching questions: {e}")
        return [], 0


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
        try:
            data = {
                'creator_id': session['user_id'],
                'title': title if title else None,
                'subject_id': subject_id,
                'question_count': question_count,
                'join_code': join_code,
                'status': 'waiting',
                'max_participants': 50,
                'time_per_question': 30,
                'current_question_index': 0,
                'question_ids': question_ids
            }
            response = supabase.table('live_quizzes').insert(data).execute()
            quiz = response.data[0] if response.data else None
            
            if quiz:
                # Add creator as a participant
                participant_data = {
                    'quiz_id': quiz['id'],
                    'student_id': session['user_id'],
                    'status': 'active'
                }
                supabase.table('live_quiz_participants').insert(participant_data).execute()
                
                flash('Quiz created successfully! Share the join code.', 'success')
                return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
            else:
                flash('Failed to create quiz. Please try again.', 'error')
                
        except Exception as e:
            print(f"Error creating quiz: {e}")
            flash('Error creating quiz. Please try again.', 'error')
    
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
    
    try:
        data = {
            'creator_id': session['user_id'],
            'title': title if title else None,
            'subject_id': subject_id,
            'question_count': available,
            'join_code': join_code,
            'status': 'waiting',
            'max_participants': 50,
            'time_per_question': 30,
            'current_question_index': 0,
            'question_ids': question_ids
        }
        response = supabase.table('live_quizzes').insert(data).execute()
        quiz = response.data[0] if response.data else None
        
        if quiz:
            # Add creator as a participant
            participant_data = {
                'quiz_id': quiz['id'],
                'student_id': session['user_id'],
                'status': 'active'
            }
            supabase.table('live_quiz_participants').insert(participant_data).execute()
            
            flash(f'Quiz created with {available} questions!', 'success')
            return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
        else:
            flash('Failed to create quiz.', 'error')
            
    except Exception as e:
        print(f"Error creating quiz: {e}")
        flash('Error creating quiz.', 'error')
    
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
        try:
            response = supabase.table('live_quizzes')\
                .select('*, subjects(name)')\
                .eq('join_code', join_code)\
                .eq('status', 'waiting')\
                .execute()
            
            if not response.data:
                flash('Invalid join code or quiz has already started.', 'error')
                return render_template('dashboard/live_quiz/join.html')
            
            quiz = response.data[0]
            
            # Check if user already joined
            participant_check = supabase.table('live_quiz_participants')\
                .select('id')\
                .eq('quiz_id', quiz['id'])\
                .eq('student_id', session['user_id'])\
                .execute()
            
            if participant_check.data:
                flash('You have already joined this quiz.', 'info')
                return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
            
            # Check if max participants reached
            participant_count = supabase.table('live_quiz_participants')\
                .select('id', count='exact')\
                .eq('quiz_id', quiz['id'])\
                .execute()
            
            if len(participant_count.data) >= quiz.get('max_participants', 50):
                flash('This quiz is full.', 'error')
                return render_template('dashboard/live_quiz/join.html')
            
            # Join the quiz
            data = {
                'quiz_id': quiz['id'],
                'student_id': session['user_id'],
                'status': 'active'
            }
            supabase.table('live_quiz_participants').insert(data).execute()
            
            flash('You have joined the quiz!', 'success')
            return redirect(url_for('live_quiz.waiting_room', quiz_id=quiz['id']))
            
        except Exception as e:
            print(f"Error joining quiz: {e}")
            flash('Error joining quiz. Please try again.', 'error')
    
    return render_template('dashboard/live_quiz/join.html')


@live_quiz_bp.route('/waiting-room/<quiz_id>')
def waiting_room(quiz_id):
    """Waiting room for a quiz"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    try:
        response = supabase.table('live_quizzes')\
            .select('*, subjects(name), creator:creator_id(first_name, last_name, public_id)')\
            .eq('id', quiz_id)\
            .execute()
        
        if not response.data:
            flash('Quiz not found.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        quiz = response.data[0]
        
        # Check if user is participant
        participant = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if not participant.data and quiz['creator_id'] != session['user_id']:
            flash('You are not a participant in this quiz.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        is_creator = quiz['creator_id'] == session['user_id']
        
        # Get all participants
        participants_response = supabase.table('live_quiz_participants')\
            .select('*, student:student_id(first_name, last_name, public_id)')\
            .eq('quiz_id', quiz_id)\
            .order('joined_at')\
            .execute()
        
        participants = participants_response.data if participants_response.data else []
        
        formatted_participants = []
        for p in participants:
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
        
    except Exception as e:
        print(f"Error loading waiting room: {e}")
        flash('Error loading quiz.', 'error')
        return redirect(url_for('live_quiz.index'))


@live_quiz_bp.route('/start/<quiz_id>', methods=['POST'])
def start_quiz(quiz_id):
    """Start a live quiz"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        # Get quiz
        response = supabase.table('live_quizzes')\
            .select('*')\
            .eq('id', quiz_id)\
            .execute()
        
        if not response.data:
            return jsonify({'error': 'Quiz not found'}), 404
        
        quiz = response.data[0]
        
        # Check if user is creator
        if quiz['creator_id'] != session['user_id']:
            return jsonify({'error': 'Only the creator can start the quiz'}), 403
        
        # Check if already started
        if quiz['status'] != 'waiting':
            return jsonify({'error': 'Quiz already started or finished'}), 400
        
        # Get participant count
        participant_response = supabase.table('live_quiz_participants')\
            .select('id', count='exact')\
            .eq('quiz_id', quiz_id)\
            .execute()
        
        participant_count = len(participant_response.data)
        
        # Minimum 2 participants
        if participant_count < 2:
            return jsonify({'error': 'Need at least 2 participants to start'}), 400
        
        # Update quiz status
        supabase.table('live_quizzes')\
            .update({
                'status': 'active',
                'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
            })\
            .eq('id', quiz_id)\
            .execute()
        
        # Reset all participants to start at question 0
        supabase.table('live_quiz_participants')\
            .update({
                'current_question_index': 0,
                'score': 0,
                'correct_count': 0,
                'wrong_count': 0,
                'skipped_count': 0,
                'answers': {},
                'ratings': {}
            })\
            .eq('quiz_id', quiz_id)\
            .execute()
        
        return jsonify({'success': True, 'quiz_id': quiz_id})
        
    except Exception as e:
        print(f"Error starting quiz: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/my-participant/<quiz_id>')
def my_participant(quiz_id):
    """Get current user's participant data"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        response = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if response.data:
            return jsonify(response.data[0])
        return jsonify({'error': 'Not a participant'}), 404
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/get-question/<quiz_id>')
def get_question(quiz_id):
    """Get current question for the user"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        # Get quiz
        quiz_response = supabase.table('live_quizzes')\
            .select('*')\
            .eq('id', quiz_id)\
            .execute()
        
        if not quiz_response.data:
            return jsonify({'error': 'Quiz not found'}), 404
        
        quiz = quiz_response.data[0]
        
        # Check if quiz is finished
        if quiz['status'] == 'finished':
            return jsonify({'completed': True, 'status': 'finished'})
        
        # If quiz is not active, return waiting status
        if quiz['status'] != 'active':
            return jsonify({'waiting': True, 'status': quiz['status']})
        
        # Get participant
        participant_response = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if not participant_response.data:
            return jsonify({'error': 'Not a participant'}), 404
        
        participant = participant_response.data[0]
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
        question_response = supabase.table('questions')\
            .select('*')\
            .eq('id', question_id)\
            .execute()
        
        if not question_response.data:
            return jsonify({'error': 'Question not found'}), 404
        
        question = question_response.data[0]
        
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
        question_response = supabase.table('questions')\
            .select('*')\
            .eq('id', question_id)\
            .execute()
        
        if not question_response.data:
            return jsonify({'error': 'Question not found'}), 404
        
        question = question_response.data[0]
        is_correct = answer == question['correct_answer']
        
        # Get participant
        participant_response = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if not participant_response.data:
            return jsonify({'error': 'Not a participant'}), 404
        
        participant = participant_response.data[0]
        
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
        
        # Update current question index
        current_index = participant.get('current_question_index', 0)
        new_index = current_index + 1
        
        supabase.table('live_quiz_participants')\
            .update({
                'answers': answers,
                'score': score,
                'correct_count': correct_count,
                'wrong_count': wrong_count,
                'current_question_index': new_index
            })\
            .eq('id', participant['id'])\
            .execute()
        
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
    """Skip a question"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    quiz_id = data.get('quiz_id')
    question_id = data.get('question_id')
    
    if not quiz_id or not question_id:
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        # Get participant
        participant_response = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if not participant_response.data:
            return jsonify({'error': 'Not a participant'}), 404
        
        participant = participant_response.data[0]
        
        # Update participant
        answers = participant.get('answers', {})
        answers[question_id] = {
            'answer': None,
            'correct': False,
            'skipped': True
        }
        
        skipped_count = participant.get('skipped_count', 0) + 1
        current_index = participant.get('current_question_index', 0)
        new_index = current_index + 1
        
        supabase.table('live_quiz_participants')\
            .update({
                'answers': answers,
                'skipped_count': skipped_count,
                'current_question_index': new_index
            })\
            .eq('id', participant['id'])\
            .execute()
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error skipping question: {e}")
        return jsonify({'error': str(e)}), 500


@live_quiz_bp.route('/submit-rating', methods=['POST'])
def submit_rating():
    """Submit HAA/MAY rating for a question"""
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
        participant_response = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if not participant_response.data:
            return jsonify({'error': 'Not a participant'}), 404
        
        participant = participant_response.data[0]
        
        # Update ratings
        ratings = participant.get('ratings', {})
        ratings[question_id] = rating
        
        supabase.table('live_quiz_participants')\
            .update({'ratings': ratings})\
            .eq('id', participant['id'])\
            .execute()
        
        return jsonify({'success': True})
        
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
        response = supabase.table('live_quiz_participants')\
            .select('*, student:student_id(first_name, last_name, public_id)')\
            .eq('quiz_id', quiz_id)\
            .order('score', desc=True)\
            .execute()
        
        participants = response.data if response.data else []
        
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
    
    try:
        response = supabase.table('live_quizzes')\
            .select('*, subjects(name)')\
            .eq('id', quiz_id)\
            .execute()
        
        if not response.data:
            flash('Quiz not found.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        quiz = response.data[0]
        
        # Check if user is participant
        participant = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if not participant.data:
            flash('You are not a participant in this quiz.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        return render_template('dashboard/live_quiz/play.html', quiz=quiz)
        
    except Exception as e:
        print(f"Error loading quiz: {e}")
        flash('Error loading quiz.', 'error')
        return redirect(url_for('live_quiz.index'))


@live_quiz_bp.route('/results/<quiz_id>')
def results(quiz_id):
    """View quiz results"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    try:
        response = supabase.table('live_quizzes')\
            .select('*, subjects(name)')\
            .eq('id', quiz_id)\
            .execute()
        
        if not response.data:
            flash('Quiz not found.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        quiz = response.data[0]
        
        is_creator = quiz['creator_id'] == session['user_id']
        
        participant = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if not participant.data and not is_creator:
            flash('You are not authorized to view these results.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        # Get all participants with scores
        participants_response = supabase.table('live_quiz_participants')\
            .select('*, student:student_id(first_name, last_name, public_id)')\
            .eq('quiz_id', quiz_id)\
            .order('score', desc=True)\
            .execute()
        
        all_participants = participants_response.data if participants_response.data else []
        
        # Get user's participant data
        user_participant = None
        for p in all_participants:
            if p['student_id'] == session['user_id']:
                user_participant = p
                break
        
        # Update rankings
        for i, p in enumerate(all_participants, 1):
            supabase.table('live_quiz_participants')\
                .update({'ranking': i})\
                .eq('id', p['id'])\
                .execute()
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
                supabase.table('live_quizzes')\
                    .update({'status': 'finished', 'ended_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})\
                    .eq('id', quiz_id)\
                    .execute()
        
        return render_template('dashboard/live_quiz/results.html',
                             quiz=quiz,
                             is_creator=is_creator,
                             participants=all_participants,
                             user_participant=user_participant)
        
    except Exception as e:
        print(f"Error loading results: {e}")
        flash('Error loading results.', 'error')
        return redirect(url_for('live_quiz.index'))


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
        quiz_response = supabase.table('live_quizzes')\
            .select('*')\
            .eq('id', quiz_id)\
            .execute()
        
        if not quiz_response.data:
            return jsonify({'error': 'Quiz not found'}), 404
        
        quiz = quiz_response.data[0]
        
        # Check if user is participant
        participant_response = supabase.table('live_quiz_participants')\
            .select('*')\
            .eq('quiz_id', quiz_id)\
            .eq('student_id', session['user_id'])\
            .execute()
        
        if not participant_response.data:
            return jsonify({'error': 'Not a participant'}), 404
        
        participant = participant_response.data[0]
        
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
                    started_at = started_at.replace('Z', '+00:00')
                    started = datetime.datetime.fromisoformat(started_at)
                else:
                    started = started_at
                elapsed = (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds()
                remaining = max(0, total_duration - elapsed)
            except Exception as e:
                print(f"Error calculating time: {e}")
                remaining = total_duration
        
        # Check if timer expired
        if remaining <= 0 and quiz.get('status') == 'active':
            # End the quiz
            supabase.table('live_quizzes')\
                .update({'status': 'finished', 'ended_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})\
                .eq('id', quiz_id)\
                .execute()
            return jsonify({'status': 'finished', 'remaining_time': 0})
        
        # Get participant progress
        current_index = participant.get('current_question_index', 0)
        is_completed = current_index >= total_questions
        
        # Get all participants for leaderboard
        all_participants = supabase.table('live_quiz_participants')\
            .select('*, student:student_id(first_name, last_name, public_id)')\
            .eq('quiz_id', quiz_id)\
            .order('score', desc=True)\
            .execute()
        
        participants_data = all_participants.data if all_participants.data else []
        
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
        quiz_response = supabase.table('live_quizzes')\
            .select('creator_id, question_ids')\
            .eq('id', quiz_id)\
            .execute()
        
        if not quiz_response.data:
            return jsonify({'error': 'Quiz not found'}), 404
        
        quiz = quiz_response.data[0]
        
        if quiz['creator_id'] != session['user_id']:
            return jsonify({'error': 'Only the creator can view analysis'}), 403
        
        question_ids = quiz.get('question_ids', [])
        
        # Get all participants' answers
        participants_response = supabase.table('live_quiz_participants')\
            .select('answers')\
            .eq('quiz_id', quiz_id)\
            .execute()
        
        participants = participants_response.data if participants_response.data else []
        
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
            q_response = supabase.table('questions')\
                .select('question_text')\
                .eq('id', qid)\
                .execute()
            
            q_text = q_response.data[0].get('question_text', 'Unknown') if q_response.data else 'Unknown'
            
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
        quiz_response = supabase.table('live_quizzes')\
            .select('*')\
            .eq('id', quiz_id)\
            .execute()
        
        if not quiz_response.data:
            flash('Quiz not found.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        quiz = quiz_response.data[0]
        
        if quiz['creator_id'] != session['user_id']:
            flash('Only the creator can export results.', 'error')
            return redirect(url_for('live_quiz.index'))
        
        # Get all participants
        participants_response = supabase.table('live_quiz_participants')\
            .select('*, student:student_id(first_name, last_name, public_id)')\
            .eq('quiz_id', quiz_id)\
            .order('score', desc=True)\
            .execute()
        
        participants = participants_response.data if participants_response.data else []
        
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