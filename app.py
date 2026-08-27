from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g
from config import Config
from db import (
    get_student_by_phone, get_student_by_id, create_student, is_admin,
    close_db_connections, init_db, ensure_wal_mode, close_db
)
from blueprints.dashboard_bp import dashboard_bp
from blueprints.groups_bp import groups_bp
from blueprints.pdfs_bp import pdfs_bp
from blueprints.admin_bp import admin_bp
from blueprints.quiz_bp import quiz_bp
from blueprints.live_quiz_bp import live_quiz_bp
from blueprints.notifications_bp import notifications_bp
from utils import format_somali_time, get_somali_time_display
import atexit
import os
import logging
import threading
import time
from datetime import datetime, timedelta

# ============================================
# BACKUP INTEGRATION
# ============================================

# Import backup manager
try:
    from backup import BackupManager
    BACKUP_AVAILABLE = True
except ImportError:
    BACKUP_AVAILABLE = False
    logging.warning("Backup module not available")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Backup configuration
BACKUP_TRIGGER_TOKEN = os.getenv('BACKUP_TRIGGER_TOKEN', 'change_this_token_in_production')
BACKUP_TRIGGER_PATH = '/backup/trigger'
BACKUP_AUTO_CHECK_HOUR = 18  # 6 PM Somali time
BACKUP_AUTO_CHECK_ENABLED = os.getenv('BACKUP_AUTO_CHECK_ENABLED', 'true').lower() == 'true'
BACKUP_LAST_RUN_FILE = os.path.join('BACKUPS', '.last_backup_run')

# Backup manager instance (lazy initialization)
_backup_manager = None

def get_backup_manager():
    global _backup_manager
    if _backup_manager is None and BACKUP_AVAILABLE:
        _backup_manager = BackupManager()
    return _backup_manager

# Backup queue (simple in‑memory)
_backup_queue = []
_backup_queue_lock = threading.Lock()

def run_backup_in_background(backup_type='daily'):
    """Run backup in a background thread."""
    def _run():
        try:
            manager = get_backup_manager()
            if manager is None:
                logger.error("Backup manager not available")
                return
            result = manager.create_backup(backup_type)
            if result['success']:
                logger.info(f"Backup successful: {result['filename']} ({result['duration']}s)")
                # Write last run timestamp
                try:
                    os.makedirs(os.path.dirname(BACKUP_LAST_RUN_FILE), exist_ok=True)
                    with open(BACKUP_LAST_RUN_FILE, 'w') as f:
                        f.write(datetime.now().isoformat())
                except Exception as e:
                    logger.warning(f"Could not write last run file: {e}")
            else:
                logger.error(f"Backup failed: {result['message']}")
        except Exception as e:
            logger.error(f"Backup thread error: {e}")
    thread = threading.Thread(target=_run)
    thread.daemon = True
    thread.start()
    logger.info(f"Backup ({backup_type}) started in background")

def trigger_backup_async(backup_type='daily'):
    """Queue a backup to run asynchronously."""
    with _backup_queue_lock:
        _backup_queue.append({'type': backup_type, 'time': datetime.now()})
    # Process queue immediately if not already running
    process_backup_queue()

def process_backup_queue():
    """Process queued backup jobs (non‑blocking)."""
    with _backup_queue_lock:
        if not _backup_queue:
            return
        # We'll process one at a time
        job = _backup_queue.pop(0)
    # Run in background
    run_backup_in_background(job['type'])

# Check for overdue backup on each request (only for a fraction of requests)
@app.before_request
def check_overdue_backup():
    """Automatically trigger a backup if it's past the scheduled time and no backup today."""
    if not BACKUP_AVAILABLE or not BACKUP_AUTO_CHECK_ENABLED:
        return

    # Only check on 10% of requests to reduce overhead
    import random
    if random.random() > 0.1:
        return

    try:
        # Get current Somali time
        from utils import get_somali_time
        now = get_somali_time()
        current_hour = now.hour

        # Check if past scheduled hour
        if current_hour >= BACKUP_AUTO_CHECK_HOUR:
            # Check if we already ran today
            last_run_date = None
            if os.path.exists(BACKUP_LAST_RUN_FILE):
                try:
                    with open(BACKUP_LAST_RUN_FILE, 'r') as f:
                        last_run_str = f.read().strip()
                        last_run = datetime.fromisoformat(last_run_str)
                        if last_run.date() == now.date():
                            # Already ran today
                            return
                except:
                    pass

            # Trigger backup
            logger.info(f"Auto‑triggering daily backup (overdue check) at {now.isoformat()}")
            trigger_backup_async('daily')
    except Exception as e:
        logger.warning(f"Error in backup overdue check: {e}")

# ============================================
# FLASK APP SETUP
# ============================================

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
app.register_blueprint(notifications_bp)

# ============================================
# TEARDOWN CONTEXT - Database cleanup
# ============================================

@app.teardown_appcontext
def close_db_connection(exception=None):
    """Close the database connection at the end of each request."""
    close_db(exception)

# ============================================
# CLEANUP ON SHUTDOWN
# ============================================

@atexit.register
def cleanup():
    """Clean up resources on shutdown."""
    logger.info("Shutdown cleanup complete.")

# ============================================
# INITIALIZE DATABASE
# ============================================

def initialize_database():
    """Initialize or repair database on startup."""
    db_path = Config.DATABASE_PATH
    if not os.path.exists(db_path):
        logger.info(f"Database not found at {db_path}. Creating new database...")
        return init_db()

    # Check existing database integrity
    try:
        from db import check_database_integrity
        is_healthy, error = check_database_integrity()
        if not is_healthy:
            logger.error(f"Database integrity check failed: {error}")
            # Try to recover or recreate
            # For now, just log and continue (backup will catch it)
    except Exception as e:
        logger.warning(f"Could not check database integrity: {e}")

    return ensure_wal_mode()

# Run database initialization
try:
    initialize_database()
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")

# ============================================
# BACKUP TRIGGER ENDPOINT
# ============================================

@app.route(BACKUP_TRIGGER_PATH, methods=['GET', 'POST'])
def trigger_backup_endpoint():
    """
    Secure endpoint to trigger a backup.
    Use with UptimeRobot or similar service to schedule daily backups.
    """
    # Security: check token
    token = request.args.get('token') or request.headers.get('X-Backup-Token')
    if token != BACKUP_TRIGGER_TOKEN:
        logger.warning(f"Unauthorized backup trigger attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401

    # Get backup type (optional)
    backup_type = request.args.get('type', 'daily')
    if backup_type not in ['daily', 'weekly', 'monthly', 'manual']:
        backup_type = 'daily'

    # Trigger backup in background
    trigger_backup_async(backup_type)

    return jsonify({
        'status': 'accepted',
        'message': f'Backup ({backup_type}) started in background',
        'timestamp': datetime.now().isoformat()
    }), 202

# ============================================
# BACKUP STATUS ENDPOINT (optional)
# ============================================

@app.route('/backup/status', methods=['GET'])
def backup_status():
    """Return backup system health status (admin only)."""
    if 'user_id' not in session or not is_admin(session['user_id']):
        return jsonify({'error': 'Unauthorized'}), 401

    if not BACKUP_AVAILABLE:
        return jsonify({'error': 'Backup module not available'}), 503

    manager = get_backup_manager()
    if manager is None:
        return jsonify({'error': 'Backup manager not available'}), 503

    health = manager.health_check()
    return jsonify(health)

# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    """Landing page - redirect to login if not logged in."""
    if 'user_id' in session:
        return redirect(url_for('dashboard.home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if 'user_id' in session:
        return redirect(url_for('dashboard.home'))

    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')

        if not phone.startswith('+252'):
            phone = '+252' + phone

        try:
            student = get_student_by_phone(phone)
        except sqlite3.DatabaseError as e:
            if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
                flash('Database error. Please contact support.', 'error')
                logger.error(f"Database corruption on login attempt: {e}")
                return render_template('login.html')
            raise

        if student:
            # Plain text password comparison (TO BE UPDATED TO HASH)
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
    """Registration page."""
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
    """Logout user."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ============================================
# CONTEXT PROCESSOR
# ============================================

@app.context_processor
def utility_processor():
    """Make session data available to all templates."""
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
    print(f"Database path: {Config.DATABASE_PATH}")
    app.run(debug=True, host='0.0.0.0', port=5000)