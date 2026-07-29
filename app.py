from flask import Flask, render_template, request, redirect, url_for, session, flash
import bcrypt
from config import Config
from supabase_client import supabase, get_student_by_phone, get_student_by_id, create_student, is_admin
from blueprints.dashboard_bp import dashboard_bp
from blueprints.groups_bp import groups_bp
from blueprints.pdfs_bp import pdfs_bp
from blueprints.admin_bp import admin_bp
from blueprints.quiz_bp import quiz_bp
from blueprints.live_quiz_bp import live_quiz_bp

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = Config.PERMANENT_SESSION_LIFETIME

# Register Blueprints
app.register_blueprint(dashboard_bp)
app.register_blueprint(groups_bp)
app.register_blueprint(pdfs_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(live_quiz_bp)  # NEW


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
            if bcrypt.checkpw(password.encode('utf-8'), student['password_hash'].encode('utf-8')):
                session['user_id'] = student['id']
                session['public_id'] = student.get('public_id', '----')
                session['user_name'] = student['first_name']
                session['user_phone'] = student['phone_number']
                session['is_admin'] = student.get('is_admin', False)
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
        
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        school_value = school_manual if school == 'manual' and school_manual else school
        
        student_data = {
            'phone_number': phone,
            'password_hash': hashed.decode('utf-8'),
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
        'is_admin': session.get('is_admin', False)
    }


# ============================================
# RUN APP
# ============================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)