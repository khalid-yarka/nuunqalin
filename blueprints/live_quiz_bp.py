from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from supabase_client import supabase, get_all_subjects
import secrets
import string
import random
import json

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
            .select('id')\
            .eq('subject_id', subject_id)\
            .execute()
        
        questions = response.data if response.data else []
        if len(questions) < limit:
            return [q['id'] for q in questions], len(questions)
        
        selected = random.sample(questions, limit)
        return [q['id'] for q in selected], limit
    except Exception as e:
        print(f"Error fetching questions: {e}")
        return [], 0


def get_subject_name(subject_id):
    """Get subject name by ID"""
    try:
        response = supabase.table('subjects').select('name').eq('id', subject_id).execute()
        if response.data:
            return response.data[0].get('name', 'Unknown')
        return 'Unknown'
    except Exception:
        return 'Unknown'


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
        question_ids, available = get_questions_for_subject(subject_id, question_count)
        
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
                # ✅ FIX: Add creator as a participant automatically
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
    
    question_ids, available = get_questions_for_subject(subject_id, question_count)
    
    if available == 0:
        flash('No questions available.', 'error')
        return redirect(url_for('live_quiz.create'))
    
    join_code = generate_unique_join_code()
    
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
            # ✅ FIX: Add creator as a participant automatically
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
    
    # Get quiz data
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
        
        # Format participants for display
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
        
        # ✅ Minimum 2 participants to start (creator + 1 other)
        if participant_count < 2:
            return jsonify({'error': 'Need at least 2 participants to start'}), 400
        
        # Update quiz status
        supabase.table('live_quizzes')\
            .update({
                'status': 'active',
                'started_at': 'now()'
            })\
            .eq('id', quiz_id)\
            .execute()
        
        return jsonify({'success': True, 'quiz_id': quiz_id})
        
    except Exception as e:
        print(f"Error starting quiz: {e}")
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
        
        return render_template('dashboard/live_quiz/results.html',
                             quiz=quiz,
                             is_creator=is_creator,
                             participants=all_participants,
                             user_participant=user_participant)
        
    except Exception as e:
        print(f"Error loading results: {e}")
        flash('Error loading results.', 'error')
        return redirect(url_for('live_quiz.index'))