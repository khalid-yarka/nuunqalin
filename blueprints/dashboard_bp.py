from flask import Blueprint, render_template, session, flash, redirect, url_for
from db import (
    get_student_by_id, get_user_quiz_history, get_user_subject_performance,
    get_user_recent_scores, get_total_correct_answers, get_distinct_subjects_attempted,
    get_user_active_quiz, get_live_quiz_by_id
)
from datetime import datetime
from services.tier_service import get_analytics_level, get_feature_level

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='')

@dashboard_bp.route('/home')
def home():
    """Dashboard home page with tier‑aware analytics"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    analytics_level = get_analytics_level(user_id)
    
    student = get_student_by_id(user_id)
    if not student:
        session.clear()
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('login'))
    
    # 1. Basic Stats (always available)
    attempts = get_user_quiz_history(user_id, 50)
    quiz_count = len(attempts)
    total_points = student.get('total_points', 0)
    
    # 2. Gamification (always available)
    level = (total_points // 10) + 1 if total_points >= 0 else 1
    xp_in_level = total_points % 10
    xp_needed = 10
    
    # 3. Performance Metrics (basic)
    total_correct = get_total_correct_answers(user_id)
    subjects_attempted = get_distinct_subjects_attempted(user_id)
    
    if attempts:
        total_questions = sum(q.get('total_questions', 10) for q in attempts)
        success_rate = round((total_correct / total_questions) * 100) if total_questions > 0 else 0
    else:
        success_rate = 0
    
    # 4. Subject Mastery Data
    subject_performance = get_user_subject_performance(user_id)
    
    # 5. Chart Data – depends on analytics level
    if analytics_level >= 2:
        recent_scores = get_user_recent_scores(user_id, 20)
    else:
        recent_scores = get_user_recent_scores(user_id, 5)
    
    chart_labels = []
    chart_data = []
    for attempt in recent_scores:
        date_str = attempt['completed_at'][:10]
        chart_labels.append(date_str)
        pct = round((attempt['score'] / attempt['total_questions']) * 100) if attempt['total_questions'] > 0 else 0
        chart_data.append(pct)
    
    # 6. Live Quiz Status (always)
    active_quiz_id = get_user_active_quiz(user_id)
    active_quiz = None
    if active_quiz_id:
        active_quiz = get_live_quiz_by_id(active_quiz_id)
    
    # 7. Recent Activity – depends on analytics level
    limit = 5 if analytics_level == 1 else 10 if analytics_level == 2 else 20
    recent_activity = []
    for q in attempts[:limit]:
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
    
    # 8. Personal Learning Insights – only for level 3
    insights = []
    if analytics_level == 3:
        # Simple insights based on subject performance
        if subject_performance:
            best = max(subject_performance, key=lambda x: x['avg_score'])
            worst = min(subject_performance, key=lambda x: x['avg_score'])
            insights.append(f"🌟 Your best subject is {best['subject_name']} with {best['avg_score']:.0f}% average.")
            insights.append(f"📚 Your weakest subject is {worst['subject_name']} with {worst['avg_score']:.0f}% average. Focus here!")
            if success_rate > 70:
                insights.append("💪 You're doing great! Keep up the consistency.")
            else:
                insights.append("🎯 Regular practice will boost your scores. Try daily quizzes.")
    
    # 9. Detailed Ranking Statistics – depends on tier level
    ranking_level = get_feature_level("detailed_ranking_stats", user_id)
    # For now, we don't have percentile data, but we can show rank if available
    
    # Greeting
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
                         active_quiz=active_quiz,
                         analytics_level=analytics_level,
                         insights=insights,
                         ranking_level=ranking_level)

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