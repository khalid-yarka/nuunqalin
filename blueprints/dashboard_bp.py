from flask import Blueprint, render_template, session, flash, redirect, url_for
from supabase_client import get_student_by_id

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='')


@dashboard_bp.route('/home')
def home():
    """Dashboard home page"""
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    return render_template('dashboard/home.html')


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