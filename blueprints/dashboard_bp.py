from flask import Blueprint, render_template, session, flash, redirect, url_for
from supabase_client import get_student_by_id, supabase
import datetime

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='')


@dashboard_bp.route('/home')
def home():
    """Dashboard home page with real stats"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Get user data
    student = get_student_by_id(user_id)
    if not student:
        session.clear()
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('login'))
    
    # Get quiz stats
    try:
        quiz_response = supabase.table('quiz_attempts')\
            .select('score, total_questions')\
            .eq('student_id', user_id)\
            .execute()
        quiz_attempts = quiz_response.data if quiz_response.data else []
    except Exception:
        quiz_attempts = []
    
    quiz_count = len(quiz_attempts)
    total_points = student.get('total_points', 0)
    
    # Calculate success rate
    if quiz_attempts:
        total_correct = sum(q.get('score', 0) for q in quiz_attempts)
        total_questions = sum(q.get('total_questions', 10) for q in quiz_attempts)
        success_rate = round((total_correct / total_questions) * 100) if total_questions > 0 else 0
    else:
        success_rate = 0
    
    # Get recent activity
    recent_activity = []
    
    # Quiz activity
    try:
        recent_quizzes = supabase.table('quiz_attempts')\
            .select('*, subjects(name)')\
            .eq('student_id', user_id)\
            .order('completed_at', desc=True)\
            .limit(5)\
            .execute()
        if recent_quizzes.data:
            for q in recent_quizzes.data:
                subject_name = q.get('subjects', {}).get('name', 'Unknown') if q.get('subjects') else 'Unknown'
                score = q.get('score', 0)
                total = q.get('total_questions', 10)
                pct = round((score / total) * 100) if total > 0 else 0
                recent_activity.append({
                    'icon': 'fa-check-circle',
                    'icon_class': 'green',
                    'title': f'Completed <span class="highlight">{subject_name}</span> Quiz',
                    'meta': f'Score: {score}/{total} ({pct}%)',
                    'time': time_ago(q.get('completed_at'))
                })
    except Exception:
        pass
    
    # PDF view activity
    try:
        recent_pdfs = supabase.table('pdfs')\
            .select('*')\
            .order('created_at', desc=True)\
            .limit(3)\
            .execute()
        if recent_pdfs.data:
            for pdf in recent_pdfs.data:
                recent_activity.append({
                    'icon': 'fa-file-pdf',
                    'icon_class': 'blue',
                    'title': f'Viewed <span class="highlight">{pdf.get("title", "PDF")}</span>',
                    'meta': '',
                    'time': time_ago(pdf.get('created_at'))
                })
    except Exception:
        pass
    
    # Sort by time (most recent first)
    recent_activity = recent_activity[:5]
    
    return render_template('dashboard/home.html',
                         student=student,
                         quiz_count=quiz_count,
                         total_points=total_points,
                         success_rate=success_rate,
                         streak=0,  # TODO: Implement streak tracking
                         recent_activity=recent_activity)


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


def time_ago(timestamp):
    """Convert timestamp to 'X ago' format"""
    if not timestamp:
        return 'Just now'
    
    try:
        # Handle different timestamp formats
        if isinstance(timestamp, str):
            if 'T' in timestamp:
                timestamp = timestamp.replace('T', ' ').split('.')[0]
            dt = datetime.datetime.fromisoformat(timestamp)
        else:
            dt = timestamp
        
        now = datetime.datetime.now()
        diff = now - dt
        
        if diff.days > 30:
            return f'{diff.days // 30} months ago'
        elif diff.days > 0:
            return f'{diff.days} days ago'
        elif diff.seconds > 3600:
            return f'{diff.seconds // 3600} hrs ago'
        elif diff.seconds > 60:
            return f'{diff.seconds // 60} min ago'
        else:
            return 'Just now'
    except Exception:
        return 'Just now'