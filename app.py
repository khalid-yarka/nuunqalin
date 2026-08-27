from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g
from config import Config
from db import (
    get_student_by_phone, get_student_by_id, create_student, is_admin,
    close_db_connections, init_db, ensure_wal_mode, close_db,
    check_database_integrity
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
import sys
import logging
import time
import secrets
from datetime import datetime
import json
from logging.handlers import RotatingFileHandler

# ============================================
# BASE DIRECTORY
# ============================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = Config.LOG_DIR

# ============================================
# LOGGING CONFIGURATION - Enhanced
# ============================================

log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s'
log_datefmt = '%Y-%m-%d %H:%M:%S'

# Ensure log directory exists
if not os.path.exists(LOG_DIR):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        pass

# Log file path
log_file = os.path.join(LOG_DIR, 'app.log')

# Rotating file handler
try:
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT
    )
    file_handler.setFormatter(logging.Formatter(log_format, log_datefmt))
    file_handler.setLevel(getattr(logging, Config.LOG_LEVEL))
except Exception as e:
    # Fallback to basic file handler if rotation fails
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter(log_format, log_datefmt))
    file_handler.setLevel(logging.WARNING)

# Console handler for errors only
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter(log_format, log_datefmt))
console_handler.setLevel(logging.ERROR)

# Request ID filter - for contextual logging
class RequestIDFilter(logging.Filter):
    def filter(self, record):
        record.request_id = getattr(g, 'request_id', 'no-req')
        return True

# Root logger
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, Config.LOG_LEVEL))
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.addFilter(RequestIDFilter())

# Suppress Flask's default logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# ============================================
# BACKUP INTEGRATION
# ============================================

try:
    from backup import BackupManager, acquire_backup_lock, release_backup_lock, is_backup_locked, BACKUP_LOCK_FILE
    BACKUP_AVAILABLE = True
except ImportError as e:
    BACKUP_AVAILABLE = False
    logger.warning(f"Backup module not available: {e}")

BACKUP_TRIGGER_TOKEN = os.getenv('BACKUP_TRIGGER_TOKEN', 'change_this_token_in_production')
BACKUP_ENABLED = os.getenv('BACKUP_ENABLED', 'true').lower() == 'true'

_backup_manager = None

def get_backup_manager():
    global _backup_manager
    if _backup_manager is None and BACKUP_AVAILABLE:
        try:
            _backup_manager = BackupManager()
        except Exception as e:
            logger.error(f"Failed to initialize backup manager: {e}")
    return _backup_manager

def execute_backup(backup_type='daily'):
    if not BACKUP_AVAILABLE:
        return {'success': False, 'message': 'Backup module not available'}
    
    try:
        manager = get_backup_manager()
        if manager is None:
            return {'success': False, 'message': 'Backup manager not available'}
        
        if is_backup_locked():
            return {'success': False, 'message': 'Backup already running'}
        
        lock_fd = acquire_backup_lock()
        if lock_fd is None:
            return {'success': False, 'message': 'Could not acquire backup lock'}
        
        try:
            result = manager.create_backup(backup_type)
            if result['success']:
                logger.info(f"Backup successful: {result['filename']} ({result['size_bytes'] / 1024:.2f} KB)")
            else:
                logger.error(f"Backup failed: {result['message']}")
            return result
        finally:
            release_backup_lock(lock_fd)
            
    except Exception as e:
        logger.error(f"Backup error: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}

# ============================================
# FLASK APP SETUP
# ============================================

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = Config.PERMANENT_SESSION_LIFETIME

app.debug = False
app.config['DEBUG'] = False
app.config['TESTING'] = False

# Session security
app.config['SESSION_COOKIE_SECURE'] = Config.SESSION_COOKIE_SECURE
app.config['SESSION_COOKIE_HTTPONLY'] = Config.SESSION_COOKIE_HTTPONLY
app.config['SESSION_COOKIE_SAMESITE'] = Config.SESSION_COOKIE_SAMESITE

# ============================================
# REQUEST CONTEXT - Request ID for logging
# ============================================

@app.before_request
def set_request_id():
    """Set a unique request ID for logging and tracking."""
    g.request_id = request.headers.get('X-Request-ID') or secrets.token_hex(8)[:8]
    g.start_time = time.time()

@app.after_request
def log_request_end(response):
    """Log requests that take longer than 1 second."""
    if hasattr(g, 'start_time'):
        duration = (time.time() - g.start_time) * 1000
        if duration > 1000:
            logger.warning(
                f"SLOW: {request.method} {request.path} {duration:.0f}ms - "
                f"status={response.status_code}"
            )
    # Add request ID to response headers
    if hasattr(g, 'request_id'):
        response.headers['X-Request-ID'] = g.request_id
    return response

# ============================================
# CSRF PROTECTION
# ============================================

@app.before_request
def generate_csrf():
    if 'user_id' in session and 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)

def validate_csrf():
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or token != session.get('csrf_token'):
        return False
    return True

# ============================================
# REGISTER BLUEPRINTS
# ============================================

app.register_blueprint(dashboard_bp)
app.register_blueprint(groups_bp)
app.register_blueprint(pdfs_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(live_quiz_bp)
app.register_blueprint(notifications_bp)

# ============================================
# TEARDOWN CONTEXT
# ============================================

@app.teardown_appcontext
def close_db_connection(exception=None):
    close_db(exception)

# ============================================
# CLEANUP ON SHUTDOWN
# ============================================

@atexit.register
def cleanup():
    logger.info("Application shutdown initiated.")
    try:
        close_db_connections()
    except Exception as e:
        logger.warning(f"Cleanup error: {e}")

# ============================================
# INITIALIZE DATABASE
# ============================================

def initialize_database():
    db_path = Config.DATABASE_PATH
    if not os.path.exists(db_path):
        logger.info(f"Database not found at {db_path}. Creating new database...")
        return init_db()

    try:
        is_healthy, error = check_database_integrity()
        if not is_healthy:
            logger.error(f"Database integrity check failed: {error}")
    except Exception as e:
        logger.warning(f"Could not check database integrity: {e}")

    return ensure_wal_mode()

try:
    initialize_database()
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")

# ============================================
# HEALTH CHECK ENDPOINT (Enhanced)
# ============================================

@app.route('/health', methods=['GET'])
def health_check():
    """
    Enhanced health check endpoint.
    Checks database, backup, and cache.
    """
    checks = {
        'database': False,
        'backup': False,
        'cache': False,
        'wal': False
    }
    details = {}
    
    # Check database connectivity
    try:
        from db import get_db
        conn = get_db()
        conn.execute("SELECT 1")
        checks['database'] = True
        
        # Check WAL mode
        cursor = conn.execute("PRAGMA journal_mode")
        result = cursor.fetchone()
        if result and result[0].upper() == 'WAL':
            checks['wal'] = True
        else:
            details['wal'] = f"WAL not enabled: {result[0] if result else 'unknown'}"
            
    except Exception as e:
        details['database'] = str(e)
        logger.error(f"Health check - database failed: {e}")
    
    # Check backup availability
    try:
        if BACKUP_AVAILABLE:
            manager = get_backup_manager()
            if manager:
                health = manager.health_check()
                checks['backup'] = health['status'] != 'critical'
                details['backup'] = health
            else:
                details['backup'] = 'Backup manager not available'
        else:
            checks['backup'] = True
            details['backup'] = 'Backup module not installed'
    except Exception as e:
        details['backup'] = str(e)
        logger.error(f"Health check - backup failed: {e}")
    
    # Check cache
    try:
        from quiz_cache import get_quiz_cache
        cache = get_quiz_cache()
        stats = cache.get_cache_stats()
        checks['cache'] = True
        details['cache'] = stats
    except Exception as e:
        details['cache'] = str(e)
        logger.error(f"Health check - cache failed: {e}")
    
    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503
    
    return jsonify({
        'status': 'healthy' if all_healthy else 'degraded',
        'checks': checks,
        'details': details,
        'timestamp': get_somali_time_display(),
        'request_id': g.request_id
    }), status_code

# ============================================
# BACKUP TRIGGER ENDPOINT (Now with warning)
# ============================================

@app.route('/backup/trigger', methods=['GET'])
def trigger_backup():
    """
    Secure endpoint to trigger a backup.
    WARNING: Running backups in web requests is not recommended.
    Use scheduled tasks/cron instead.
    """
    if not BACKUP_ENABLED:
        return jsonify({
            'status': 'disabled',
            'message': 'Backup system is disabled'
        }), 503

    token = request.args.get('token')
    if token != BACKUP_TRIGGER_TOKEN:
        logger.warning(f"Unauthorized backup trigger attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401

    backup_type = request.args.get('type', 'daily')
    if backup_type not in ['daily', 'weekly', 'monthly', 'manual']:
        backup_type = 'daily'

    if not BACKUP_AVAILABLE:
        return jsonify({
            'status': 'error',
            'message': 'Backup module not available'
        }), 503

    if is_backup_locked():
        return jsonify({
            'status': 'skipped',
            'message': 'Backup already running',
            'timestamp': get_somali_time_display()
        }), 409

    start_time = time.time()
    result = execute_backup(backup_type)
    duration = time.time() - start_time

    if result and result['success']:
        return jsonify({
            'status': 'success',
            'message': f'Backup created: {result["filename"]}',
            'filename': result['filename'],
            'size_kb': round(result['size_bytes'] / 1024, 2),
            'duration_seconds': round(duration, 2),
            'timestamp': get_somali_time_display(),
            'warning': 'Web-triggered backups are not recommended. Use scheduled tasks.'
        }), 200
    else:
        error_msg = result.get('message', 'Backup failed') if result else 'Backup failed'
        return jsonify({
            'status': 'error',
            'message': error_msg,
            'timestamp': get_somali_time_display()
        }), 500


@app.route('/backup/status', methods=['GET'])
def backup_status():
    if 'user_id' not in session or not is_admin(session['user_id']):
        return jsonify({'error': 'Unauthorized'}), 401

    if not BACKUP_AVAILABLE:
        return jsonify({'error': 'Backup module not available'}), 503

    manager = get_backup_manager()
    if manager is None:
        return jsonify({'error': 'Backup manager not available'}), 503

    try:
        health = manager.health_check()
        return jsonify(health)
    except Exception as e:
        logger.error(f"Backup status error: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================
# ROUTES (Login, Register, Logout)
# ============================================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard.home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard.home'))

    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')

        if not phone.startswith('+252'):
            phone = '+252' + phone

        try:
            student = get_student_by_phone(phone)
        except Exception as e:
            if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
                logger.error(f"Database corruption on login attempt: {e}")
                flash('Database error. Please contact support.', 'error')
                return render_template('login.html')
            logger.error(f"Login error: {e}")
            flash('An error occurred. Please try again.', 'error')
            return render_template('login.html')

        if student:
            if password == student['password']:
                session['user_id'] = student['id']
                session['public_id'] = student.get('public_id', '----')
                session['user_name'] = student['first_name']
                session['user_phone'] = student['phone_number']
                session['is_admin'] = bool(student.get('is_admin', 0))
                session.permanent = True
                session['csrf_token'] = secrets.token_hex(32)
                logger.info(f"User logged in: user_id={student['id']}")
                flash('Welcome back!', 'success')
                return redirect(url_for('dashboard.home'))
            else:
                flash('Invalid password. Please try again.', 'error')
        else:
            flash('No account found with this phone number.', 'error')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
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
            'password': password,
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
            logger.info(f"New user registered: {phone}")
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Registration failed. Please try again.', 'error')

    return render_template('register.html')

@app.route('/logout')
def logout():
    logger.info(f"User logged out: user_id={session.get('user_id')}")
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ============================================
# CONTEXT PROCESSOR
# ============================================

@app.context_processor
def utility_processor():
    return {
        'session': session,
        'is_admin': session.get('is_admin', False),
        'somali_time': get_somali_time_display,
        'csrf_token': session.get('csrf_token', '')
    }

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def page_not_found(e):
    logger.warning(f"404: {request.path} from {request.remote_addr}")
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"500: {request.path} - {e}", exc_info=True)
    return render_template('500.html'), 500

@app.errorhandler(403)
def forbidden(e):
    logger.warning(f"403: {request.path} from {request.remote_addr}")
    return render_template('403.html'), 403

# ============================================
# RUN APP
# ============================================

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    print(f"Server starting at: {get_somali_time_display()}")
    print(f"Database path: {Config.DATABASE_PATH}")
    print(f"Log directory: {Config.LOG_DIR}")
    print(f"Backup directory: {Config.BACKUP_DIR}")
    print(f"Debug mode: {debug_mode}")
    print(f"Request ID: {g.request_id if hasattr(g, 'request_id') else 'N/A'}")
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))