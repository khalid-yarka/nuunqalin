from flask import Blueprint, render_template, session, flash, redirect, url_for
from db import (
    get_student_by_id, get_user_quiz_history, get_user_subject_performance,
    get_user_recent_scores, get_total_correct_answers, get_distinct_subjects_attempted,
    get_user_active_quiz, get_live_quiz_by_id
)
from datetime import datetime

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='')

@dashboard_bp.route('/home')
def home():
    """Dashboard home page with advanced analytics and gamification"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    student = get_student_by_id(user_id)
    if not student:
        session.clear()
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('login'))
    
    # 1. Basic Stats
    attempts = get_user_quiz_history(user_id, 50)
    quiz_count = len(attempts)
    total_points = student.get('total_points', 0)
    
    # 2. Gamification (Level & XP)
    level = (total_points // 10) + 1 if total_points >= 0 else 1
    xp_in_level = total_points % 10
    xp_needed = 10
    
    # 3. Performance Metrics
    total_correct = get_total_correct_answers(user_id)
    subjects_attempted = get_distinct_subjects_attempted(user_id)
    
    if attempts:
        total_questions = sum(q.get('total_questions', 10) for q in attempts)
        success_rate = round((total_correct / total_questions) * 100) if total_questions > 0 else 0
    else:
        success_rate = 0
    
    # 4. Subject Mastery Data
    subject_performance = get_user_subject_performance(user_id)
    
    # 5. Chart Data (Last 10 attempts)
    recent_scores = get_user_recent_scores(user_id, 10)
    chart_labels = []
    chart_data = []
    for attempt in recent_scores:
        date_str = attempt['completed_at'][:10]
        chart_labels.append(date_str)
        pct = round((attempt['score'] / attempt['total_questions']) * 100) if attempt['total_questions'] > 0 else 0
        chart_data.append(pct)
    
    # 6. Live Quiz Status
    active_quiz_id = get_user_active_quiz(user_id)
    active_quiz = None
    if active_quiz_id:
        active_quiz = get_live_quiz_by_id(active_quiz_id)
    
    # 7. Recent Activity (Enhanced)
    recent_activity = []
    for q in attempts[:5]:
        subject_name = q.get('subjects', {}).get('name', 'Unknown') if q.get('subjects') else 'Unknown'
        score = q.get('score', 0)
        total = q.get('total_questions', 10)
        pct = round((score / total) * 100) if total > 0 else 0
        recent_activity.append({
            'type': 'quiz',
            'icon': 'fa-check-circle',
            'color': 'green',
            'title': f'Completed <strong>{subject_name}</strong> Quiz',
            'meta': f'Score: {score}/{total} ({pct}%)',
            'points': f'+{score} XP',
            'time': 'Recently'
        })
    
    # 8. Greeting based on time
    hour = datetime.now().hour
    if hour < 12:
        greeting = "🌅 Good Morning"
    elif hour < 17:
        greeting = "☀️ Good Afternoon"
    else:
        greeting = "🌙 Good Evening"
    
    return render_template('dashboard/home.html',
                         student=student,
                         greeting=greeting,
                         level=level,
                         xp_in_level=xp_in_level,
                         xp_needed=xp_needed,
                         quiz_count=quiz_count,
                         total_points=total_points,
                         total_correct=total_correct,
                         subjects_attempted=subjects_attempted,
                         success_rate=success_rate,
                         streak=0,
                         recent_activity=recent_activity,
                         subject_performance=subject_performance,
                         chart_labels=chart_labels,
                         chart_data=chart_data,
                         active_quiz=active_quiz)

@dashboard_bp.route('/profile')
def profile():
    """User profile page"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    student = get_student_by_id(session['user_id'])
    
    if not student:
        session.clear()
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('login'))
    
    return render_template('dashboard/profile.html', student=student)