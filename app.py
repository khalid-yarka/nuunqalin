from flask import Flask, render_template, request, redirect, url_for, session, flash
from config import Config
from db import get_student_by_phone, get_student_by_id, create_student, is_admin, close_db_connections
from blueprints.dashboard_bp import dashboard_bp
from blueprints.groups_bp import groups_bp
from blueprints.pdfs_bp import pdfs_bp
from blueprints.admin_bp import admin_bp
from blueprints.quiz_bp import quiz_bp
from blueprints.live_quiz_bp import live_quiz_bp
from blueprints.notifications_bp import notifications_bp
from utils import format_somali_time, get_somali_time_display
import atexit

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = Config.PERMANENT_SESSION_LIFETIME

# Register Blueprints
app.register_blueprint(dashboard_bp)
app.register_blueprint(groups_bp)
app.register_blueprint(pdfs_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(live_quiz_bp)
app.register_blueprint(notifications_bp)  # NEW


# ============================================
# CLEANUP ON SHUTDOWN
# ============================================

@atexit.register
def cleanup():
    """Close database connections on shutdown"""
    close_db_connections()
    print("Database connections closed.")


# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    """Landing page - redirect to login if not logged in"""
    if 'user_id' in session:
        return redirect(url_for('dashboard.home'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if 'user_id' in session:
        return redirect(url_for('dashboard.home'))
    
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        
        if not phone.startswith('+252'):
            phone = '+252' + phone
        
        student = get_student_by_phone(phone)
        
        if student:
            # Plain text password comparison (NO HASHING - TO BE UPDATED)
            if password == student['password']:
                session['user_id'] = student['id']
                session['public_id'] = student.get('public_id', '----')
                session['user_name'] = student['first_name']
                session['user_phone'] = student['phone_number']
                session['is_admin'] = bool(student.get('is_admin', 0))
                session.permanent = True
                flash('Welcome back!', 'success')
                return redirect(url_for('dashboard.home'))
            else:
                flash('Invalid password. Please try again.', 'error')
        else:
            flash('No account found with this phone number.', 'error')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration page"""
    if 'user_id' in session:
        return redirect(url_for('dashboard.home'))
    
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        first_name = request.form.get('first_name', '').strip()
        middle_name = request.form.get('middle_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        location = request.form.get('location', '')
        city = request.form.get('city', '').strip()
        school = request.form.get('school', '')
        school_manual = request.form.get('school_manual', '').strip()
        grade = request.form.get('grade', '')
        
        if not phone.startswith('+252'):
            phone = '+252' + phone
        
        existing = get_student_by_phone(phone)
        if existing:
            flash('This phone number is already registered.', 'error')
            return render_template('register.html')
        
        school_value = school_manual if school == 'manual' and school_manual else school
        
        student_data = {
            'phone_number': phone,
            'password': password,  # Plain text - WILL BE UPDATED TO HASH
            'first_name': first_name,
            'middle_name': middle_name,
            'last_name': last_name,
            'location': location,
            'city': city,
            'school': school_value,
            'grade': grade,
            'total_points': 0
        }
        
        new_student = create_student(student_data)
        
        if new_student:
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Registration failed. Please try again.', 'error')
    
    return render_template('register.html')


@app.route('/logout')
def logout():
    """Logout user"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ============================================
# CONTEXT PROCESSOR
# ============================================

@app.context_processor
def utility_processor():
    """Make session data available to all templates"""
    return {
        'session': session,
        'is_admin': session.get('is_admin', False),
        'somali_time': get_somali_time_display
    }


# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403


# ============================================
# RUN APP
# ============================================

if __name__ == '__main__':
    print(f"Server starting at: {get_somali_time_display()}")
    app.run(debug=True, host='0.0.0.0', port=5000)