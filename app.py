# ============================================
# NUUNPLATFORM - MAIN APPLICATION
# ============================================

import os
import sys
import time
import secrets
import logging
import atexit
from datetime import datetime
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g

from config import Config
from db import (
    get_student_by_phone, get_student_by_id, create_student, is_admin,
    close_db_connections, close_db,
)
from utils import get_somali_time_display
from startup import verify_startup, get_startup_health
from database import get_database_health
from errors import register_error_handlers
from error_models import get_error_stats, get_error_log_count

# ============================================
# BLUEPRINT IMPORTS
# ============================================

from blueprints.dashboard_bp import dashboard_bp
from blueprints.groups_bp import groups_bp
from blueprints.pdfs_bp import pdfs_bp
from blueprints.admin_bp import admin_bp
from blueprints.admin_errors_bp import admin_errors_bp
from blueprints.quiz_bp import quiz_bp
from blueprints.live_quiz_bp import live_quiz_bp
from blueprints.notifications_bp import notifications_bp
from blueprints.user_settings_bp import user_settings_bp

# NEW: Activity & Backup blueprints
from blueprints.admin_activity_bp import admin_activity_bp
from blueprints.admin_backup_bp import admin_backup_bp

# NEW: Activity logger
from activity_logger import log_activity, log_admin_action, log_quiz_complete, log_backup_event

# ============================================ii
# BASE DIRECTORY & LOGGING
# ============================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = Config.LOG_DIR

if not os.path.exists(LOG_DIR):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        pass

# ============================================
# REQUEST ID FILTER
# ============================================

class RequestIDFilter(logging.Filter):
    def filter(self, record):
        try:
            record.request_id = getattr(g, 'request_id', 'no-req')
        except RuntimeError:
            record.request_id = 'no-req'
        return True

# ============================================
# LOGGING SETUP
# ============================================

log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s'
log_datefmt = '%Y-%m-%d %H:%M:%S'

log_file = os.path.join(LOG_DIR, 'app.log')
try:
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT
    )
    file_handler.setFormatter(logging.Formatter(log_format, log_datefmt))
    file_handler.setLevel(getattr(logging, Config.LOG_LEVEL, logging.WARNING))
except Exception:
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter(log_format, log_datefmt))
    file_handler.setLevel(logging.WARNING)

error_log_file = os.path.join(LOG_DIR, 'error.log')
try:
    error_file_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT
    )
    error_file_handler.setFormatter(logging.Formatter(log_format, log_datefmt))
    error_file_handler.setLevel(logging.ERROR)
except Exception:
    error_file_handler = logging.FileHandler(error_log_file)
    error_file_handler.setFormatter(logging.Formatter(log_format, log_datefmt))
    error_file_handler.setLevel(logging.ERROR)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter(log_format, log_datefmt))
console_handler.setLevel(logging.ERROR)

request_id_filter = RequestIDFilter()
for handler in [file_handler, error_file_handler, console_handler]:
    handler.addFilter(request_id_filter)

root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, Config.LOG_LEVEL, logging.WARNING))
root_logger.addHandler(file_handler)
root_logger.addHandler(error_file_handler)
root_logger.addHandler(console_handler)

logging.getLogger('werkzeug').setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# ============================================
# STARTUP VERIFICATION
# ============================================

logger.info("=" * 60)
logger.info("NUUNPLATFORM STARTUP - Starting verification")
logger.info("=" * 60)

if not verify_startup():
    logger.critical("=" * 60)
    logger.critical("STARTUP VERIFICATION FAILED")
    logger.critical("Application cannot start. Please check the logs.")
    logger.critical("=" * 60)
    sys.exit(1)

logger.info("Startup verification PASSED")
logger.info("=" * 60)

# ============================================
# BACKUP INTEGRATION
# ============================================

BACKUP_AVAILABLE = False
BACKUP_LOCK_FILE = None
try:
    from backup import BackupManager, acquire_backup_lock, release_backup_lock, is_backup_locked, BACKUP_LOCK_FILE
    BACKUP_AVAILABLE = True
except ImportError as e:
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
# CACHE INITIALIZATION
# ============================================

try:
    from cache import get_cache_manager, start_worker
    cache_manager = get_cache_manager()
    logger.info("Cache manager initialized successfully.")

    if Config.REDIS_URL and Config.REDIS_URL.strip():
        if os.getenv('CACHE_WORKER_ENABLED', 'true').lower() == 'true':
            start_worker()
            logger.info("Cache worker started.")
        else:
            logger.info("Cache worker disabled via environment variable.")
    else:
        logger.info("Redis not configured; cache worker not started.")
except Exception as e:
    logger.error(f"Cache initialization failed: {e}")

# ============================================
# FLASK APP
# ============================================

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = Config.PERMANENT_SESSION_LIFETIME
app.debug = False
app.config['DEBUG'] = False
app.config['TESTING'] = False

app.config['SESSION_COOKIE_SECURE'] = Config.SESSION_COOKIE_SECURE
app.config['SESSION_COOKIE_HTTPONLY'] = Config.SESSION_COOKIE_HTTPONLY
app.config['SESSION_COOKIE_SAMESITE'] = Config.SESSION_COOKIE_SAMESITE

# ============================================
# REQUEST CONTEXT
# ============================================

@app.before_request
def set_request_id():
    g.request_id = request.headers.get('X-Request-ID') or secrets.token_hex(8)[:8]
    g.start_time = time.time()

@app.after_request
def log_request_end(response):
    if hasattr(g, 'start_time'):
        duration = (time.time() - g.start_time) * 1000
        if duration > 1000:
            logger.warning(
                f"SLOW: {request.method} {request.path} {duration:.0f}ms - "
                f"status={response.status_code}"
            )
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
app.register_blueprint(admin_errors_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(live_quiz_bp)
app.register_blueprint(notifications_bp)

# NEW: Activity & Backup
app.register_blueprint(admin_activity_bp)
app.register_blueprint(admin_backup_bp)

app.register_blueprint(user_settings_bp)

# ============================================
# REGISTER ERROR HANDLERS
# ============================================

register_error_handlers(app)

# ============================================
# TEARDOWN
# ============================================

@app.teardown_appcontext
def close_db_connection(exception=None):
    close_db(exception)

@atexit.register
def cleanup():
    logger.info("Application shutdown initiated.")
    try:
        close_db_connections()
    except Exception as e:
        logger.warning(f"Cleanup error: {e}")

# ============================================
# ROUTES
# ============================================

@app.route('/health', methods=['GET'])
def health_check():
    db_health = get_database_health()
    startup_health = get_startup_health()

    backup_health = {'status': 'unknown'}
    if BACKUP_AVAILABLE:
        try:
            manager = get_backup_manager()
            if manager:
                backup_health = manager.health_check()
            else:
                backup_health = {'status': 'error', 'issues': ['Backup manager unavailable']}
        except Exception as e:
            backup_health = {'status': 'error', 'issues': [str(e)]}
    else:
        backup_health = {'status': 'disabled'}

    cache_health = {'status': 'unknown'}
    try:
        from cache import get_cache_manager
        cache = get_cache_manager()
        stats = cache.get_metrics()
        cache_health = {'status': 'healthy', 'stats': stats}
    except Exception as e:
        cache_health = {'status': 'error', 'error': str(e)}

    error_stats = get_error_stats()

    critical_issues = []
    if not db_health.get('exists'):
        critical_issues.append('Database does not exist')
    if not db_health.get('openable'):
        critical_issues.append('Database cannot be opened')
    if not db_health.get('integrity'):
        critical_issues.append('Database integrity check failed')
    if not db_health.get('tables_ok'):
        critical_issues.append('Missing required tables')
    if not db_health.get('wal_enabled'):
        critical_issues.append('WAL mode is disabled')

    is_healthy = len(critical_issues) == 0
    status_code = 200 if is_healthy else 503

    return jsonify({
        'status': 'healthy' if is_healthy else 'critical',
        'timestamp': get_somali_time_display(),
        'request_id': getattr(g, 'request_id', 'no-req'),
        'components': {
            'database': {
                'exists': db_health.get('exists'),
                'openable': db_health.get('openable'),
                'writable': db_health.get('writable'),
                'integrity': db_health.get('integrity'),
                'wal_enabled': db_health.get('wal_enabled'),
                'tables_ok': db_health.get('tables_ok'),
                'columns_ok': db_health.get('columns_ok'),
                'errors': db_health.get('errors', [])
            },
            'backup': backup_health,
            'cache': cache_health,
            'errors': {
                'total': error_stats.get('total', 0),
                'critical': error_stats.get('critical', 0),
                'unresolved': error_stats.get('unresolved', 0)
            }
        },
        'critical_issues': critical_issues
    }), status_code

@app.route('/docs')
def docs():
    return render_template('docs.html')

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

                # Log activity
                log_activity('user.login', f"User {student['id']} logged in", 'info', user_id=student['id'])

                return redirect(url_for('dashboard.home'))
            else:
                flash('Invalid password. Please try again.', 'error')
                log_activity('user.login', f"Failed login attempt for {phone}", 'warning')
        else:
            flash('No account found with this phone number.', 'error')
            log_activity('user.login', f"Unknown phone {phone} tried to login", 'warning')

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

        # ============================================
        # SERVER-SIDE NAME VALIDATION (Strict)
        # ============================================
        def validate_name(name):
            if not name or len(name) < 4:
                return False
            if any(char.isdigit() for char in name):
                return False
            return True

        if not validate_name(first_name):
            logger.warning(f"Registration failed: Invalid first_name '{first_name}'")
            flash('Registration failed. Please check your details.', 'error')
            return render_template('register.html')

        if not validate_name(last_name):
            logger.warning(f"Registration failed: Invalid last_name '{last_name}'")
            flash('Registration failed. Please check your details.', 'error')
            return render_template('register.html')

        if len(password) < 8:
            flash('Registration failed. Please check your details.', 'error')
            return render_template('register.html')

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
            log_activity('user.register', f"New user registered: {new_student['id']}", 'info', user_id=new_student['id'])
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Registration failed. Please try again.', 'error')

    return render_template('register.html')

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    logger.info(f"User logged out: user_id={user_id}")
    if user_id:
        log_activity('user.logout', f"User {user_id} logged out", 'info', user_id=user_id)
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ============================================
# BACKUP TRIGGER ENDPOINTS
# ============================================

@app.route('/backup/trigger', methods=['GET'])
def trigger_backup():
    if not BACKUP_ENABLED:
        return jsonify({'status': 'disabled', 'message': 'Backup system is disabled'}), 503

    token = request.args.get('token')
    if token != BACKUP_TRIGGER_TOKEN:
        logger.warning(f"Unauthorized backup trigger attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401

    backup_type = request.args.get('type', 'daily')
    if backup_type not in ['daily', 'weekly', 'monthly', 'manual']:
        backup_type = 'daily'

    if not BACKUP_AVAILABLE:
        return jsonify({'status': 'error', 'message': 'Backup module not available'}), 503

    if is_backup_locked():
        return jsonify({'status': 'skipped', 'message': 'Backup already running'}), 409

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
        return jsonify({'status': 'error', 'message': error_msg}), 500

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
# RUN APP
# ============================================

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    print(f"Server starting at: {get_somali_time_display()}")
    print(f"Database path: {Config.DATABASE_PATH}")
    print(f"Log directory: {Config.LOG_DIR}")
    print(f"Backup directory: {Config.BACKUP_DIR}")
    print(f"Redis URL: {Config.REDIS_URL or 'Not configured'}")
    print(f"Debug mode: {debug_mode}")
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))