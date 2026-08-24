from flask import Blueprint, render_template, session, flash, redirect, url_for
from db import get_student_by_id, get_user_quiz_history

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='')

@dashboard_bp.route('/home')
def home():
    """Dashboard home page with real stats"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    student = get_student_by_id(user_id)
    if not student:
        session.clear()
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('login'))
    
    attempts = get_user_quiz_history(user_id, 50)
    
    quiz_count = len(attempts)
    total_points = student.get('total_points', 0)
    
    if attempts:
        total_correct = sum(q.get('score', 0) for q in attempts)
        total_questions = sum(q.get('total_questions', 10) for q in attempts)
        success_rate = round((total_correct / total_questions) * 100) if total_questions > 0 else 0
    else:
        success_rate = 0
    
    recent_activity = []
    for q in attempts[:5]:
        subject_name = q.get('subjects', {}).get('name', 'Unknown') if q.get('subjects') else 'Unknown'
        score = q.get('score', 0)
        total = q.get('total_questions', 10)
        pct = round((score / total) * 100) if total > 0 else 0
        recent_activity.append({
            'icon': 'fa-check-circle',
            'icon_class': 'green',
            'title': f'Completed <span class="highlight">{subject_name}</span> Quiz',
            'meta': f'Score: {score}/{total} ({pct}%)',
            'time': 'Recently'
        })
    
    return render_template('dashboard/home.html',
                         student=student,
                         quiz_count=quiz_count,
                         total_points=total_points,
                         success_rate=success_rate,
                         streak=0,
                         recent_activity=recent_activity[:5])

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