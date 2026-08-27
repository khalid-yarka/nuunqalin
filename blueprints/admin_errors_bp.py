# ============================================
# ADMIN ERROR DASHBOARD BLUEPRINT
# ============================================
# Secure admin interface for viewing and managing errors
# ============================================

from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify, abort
from functools import wraps
from config import Config
from error_models import (
    get_error_logs, get_error_log_count, get_error_log_by_id,
    get_error_log_by_request_id, resolve_error_log, dismiss_error_log,
    clear_resolved_errors, get_error_stats, clean_old_errors
)
import secrets
import time
import hashlib
import logging

logger = logging.getLogger(__name__)

admin_errors_bp = Blueprint('admin_errors', __name__, url_prefix='/admin/errors')

# ============================================
# ADMIN AUTHENTICATION
# ============================================

ADMIN_SESSION_KEY = 'admin_error_session'
ADMIN_SESSION_EXPIRY = Config.ADMIN_SESSION_TIMEOUT

# Simple rate limiting for login attempts
_login_attempts = {}
_last_cleanup = time.time()


def check_login_rate_limit(ip: str) -> bool:
    """Check if login attempts from this IP exceed rate limit."""
    global _login_attempts, _last_cleanup
    
    # Cleanup old entries every 5 minutes
    if time.time() - _last_cleanup > 300:
        _login_attempts = {}
        _last_cleanup = time.time()
    
    # Get attempts for this IP
    attempts = _login_attempts.get(ip, [])
    # Remove attempts older than 15 minutes
    attempts = [t for t in attempts if time.time() - t < 900]
    _login_attempts[ip] = attempts
    
    # Max 5 attempts per 15 minutes
    return len(attempts) < 5


def record_login_attempt(ip: str) -> None:
    """Record a login attempt from this IP."""
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(time.time())


def admin_required(f):
    """Decorator to require admin authentication for error dashboard."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if admin is logged in
        if not session.get(ADMIN_SESSION_KEY):
            flash('Please login to access the error dashboard.', 'warning')
            return redirect(url_for('admin_errors.login'))
        
        # Check session expiry
        login_time = session.get('admin_login_time', 0)
        if time.time() - login_time > ADMIN_SESSION_EXPIRY:
            session.pop(ADMIN_SESSION_KEY, None)
            session.pop('admin_login_time', None)
            flash('Session expired. Please login again.', 'warning')
            return redirect(url_for('admin_errors.login'))
        
        return f(*args, **kwargs)
    return decorated_function


# ============================================
# LOGIN / LOGOUT
# ============================================

@admin_errors_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login page for error dashboard."""
    # If already logged in, redirect to dashboard
    if session.get(ADMIN_SESSION_KEY):
        return redirect(url_for('admin_errors.index'))
    
    # Check rate limit
    ip = request.remote_addr or 'unknown'
    if not check_login_rate_limit(ip):
        flash('Too many login attempts. Please try again later.', 'error')
        return render_template('dashboard/admin/error_login.html')
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        csrf_token = request.form.get('csrf_token', '')
        
        # Validate CSRF token
        if csrf_token != session.get('admin_csrf_token'):
            flash('Invalid request. Please try again.', 'error')
            return render_template('dashboard/admin/error_login.html')
        
        record_login_attempt(ip)
        
        # Check password against config
        if password and password == Config.ADMIN_ERROR_PASSWORD:
            # Login successful
            session[ADMIN_SESSION_KEY] = True
            session['admin_login_time'] = time.time()
            session['admin_csrf_token'] = secrets.token_hex(32)
            
            logger.info(f"Admin error dashboard login successful from {ip}")
            flash('Welcome to the Error Dashboard.', 'success')
            return redirect(url_for('admin_errors.index'))
        else:
            flash('Invalid password.', 'error')
            logger.warning(f"Failed admin login attempt from {ip}")
    
    # Generate CSRF token for login form
    session['admin_csrf_token'] = secrets.token_hex(32)
    
    return render_template('dashboard/admin/error_login.html', 
                         csrf_token=session['admin_csrf_token'])


@admin_errors_bp.route('/logout')
def logout():
    """Logout from admin error dashboard."""
    session.pop(ADMIN_SESSION_KEY, None)
    session.pop('admin_login_time', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('admin_errors.login'))


# ============================================
# ERROR DASHBOARD
# ============================================

@admin_errors_bp.route('/')
@admin_required
def index():
    """Main error dashboard page."""
    # Get filter parameters
    severity = request.args.get('severity')
    resolved = request.args.get('resolved')
    search = request.args.get('search', '').strip()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    
    # Convert resolved filter
    resolved_filter = None
    if resolved == '1':
        resolved_filter = 1
    elif resolved == '0':
        resolved_filter = 0
    
    # Get errors
    offset = (page - 1) * per_page
    errors = get_error_logs(
        limit=per_page,
        offset=offset,
        severity=severity,
        resolved=resolved_filter,
        search=search
    )
    
    # Get total count for pagination
    total = get_error_log_count(
        severity=severity,
        resolved=resolved_filter,
        search=search
    )
    
    # Get statistics
    stats = get_error_stats()
    
    # Clean old errors
    try:
        cleaned = clean_old_errors()
        if cleaned > 0:
            logger.info(f"Cleaned {cleaned} old errors")
    except Exception as e:
        logger.error(f"Error cleaning old errors: {e}")
    
    return render_template(
        'dashboard/admin/error_list.html',
        errors=errors,
        stats=stats,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page if total > 0 else 1,
        severity=severity,
        resolved=resolved,
        search=search,
        csrf_token=session.get('admin_csrf_token', '')
    )


@admin_errors_bp.route('/<error_id>')
@admin_required
def detail(error_id):
    """View detailed error information."""
    error = get_error_log_by_id(error_id)
    
    if not error:
        flash('Error not found.', 'error')
        return redirect(url_for('admin_errors.index'))
    
    return render_template(
        'dashboard/admin/error_detail.html',
        error=error,
        csrf_token=session.get('admin_csrf_token', '')
    )


@admin_errors_bp.route('/by-request/<request_id>')
@admin_required
def by_request(request_id):
    """View error by request ID."""
    error = get_error_log_by_request_id(request_id)
    
    if not error:
        flash('Error not found.', 'error')
        return redirect(url_for('admin_errors.index'))
    
    return redirect(url_for('admin_errors.detail', error_id=error['id']))


# ============================================
# ERROR ACTIONS (AJAX)
# ============================================

@admin_errors_bp.route('/resolve/<error_id>', methods=['POST'])
@admin_required
def resolve(error_id):
    """Mark an error as resolved."""
    # Validate CSRF
    token = request.form.get('csrf_token')
    if token != session.get('admin_csrf_token'):
        return jsonify({'error': 'CSRF validation failed'}), 403
    
    note = request.form.get('note', '').strip()
    
    if resolve_error_log(error_id, note):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to resolve error'}), 500


@admin_errors_bp.route('/dismiss/<error_id>', methods=['POST'])
@admin_required
def dismiss(error_id):
    """Dismiss an error."""
    # Validate CSRF
    token = request.form.get('csrf_token')
    if token != session.get('admin_csrf_token'):
        return jsonify({'error': 'CSRF validation failed'}), 403
    
    if dismiss_error_log(error_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to dismiss error'}), 500


@admin_errors_bp.route('/clear-resolved', methods=['POST'])
@admin_required
def clear_resolved():
    """Clear all resolved errors."""
    # Validate CSRF
    token = request.form.get('csrf_token')
    if token != session.get('admin_csrf_token'):
        return jsonify({'error': 'CSRF validation failed'}), 403
    
    count = clear_resolved_errors()
    return jsonify({'success': True, 'deleted': count})


@admin_errors_bp.route('/stats')
@admin_required
def stats():
    """Get error statistics as JSON."""
    return jsonify(get_error_stats())


# ============================================
# USER ERROR REPORTING
# ============================================

@admin_errors_bp.route('/report', methods=['GET', 'POST'])
def report():
    """
    User-facing error report form.
    Users can report problems they encountered.
    """
    request_id = request.args.get('id') or getattr(g, 'request_id', None)
    
    if request.method == 'POST':
        description = request.form.get('description', '').strip()
        email = request.form.get('email', '').strip()
        request_id = request.form.get('request_id', '').strip()
        url = request.form.get('url', '').strip()
        
        if not description:
            flash('Please describe what you were doing.', 'error')
            return render_template('report_error.html', 
                                 request_id=request_id,
                                 email=email)
        
        # Try to get the actual error from database
        error_data = None
        if request_id:
            error = get_error_log_by_request_id(request_id)
            if error:
                error_data = error
        
        # If no error in database, create a new error log
        if not error_data:
            from errors import handle_error
            error_data = handle_error(
                Exception("User Reported Error"),
                status_code=500,
                severity='WARNING',
                user_description=description
            )
            error_data['request_id'] = request_id or error_data.get('request_id', 'no-req')
        
        # Update error with user description
        if error_data and error_data.get('id'):
            try:
                from error_models import store_error_log
                # Update the existing error log with user description
                conn = get_db()
                conn.execute(
                    "UPDATE error_logs SET user_description = ? WHERE id = ?",
                    (description, error_data['id'])
                )
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to update error with user description: {e}")
        
        # Send email with user report
        try:
            from errors import send_error_email
            send_error_email({
                'request_id': request_id or 'no-req',
                'timestamp': __import__('datetime').datetime.now().isoformat(),
                'severity': 'WARNING',
                'status_code': 500,
                'url': url or 'N/A',
                'method': 'REPORT',
                'user_id': session.get('user_id'),
                'ip_address': request.remote_addr,
                'error_type': 'UserReportedError',
                'error_message': description[:1000],
                'stack_trace': f'User reported: {description[:500]}\n\nEmail: {email or "Not provided"}',
                'user_description': description,
                'occurrence_count': 1,
                'error_hash': 'user_report_' + str(int(time.time()))
            })
        except Exception as e:
            logger.error(f"Failed to send user report email: {e}")
        
        flash('Thank you for your report. We will look into this issue.', 'success')
        return redirect(url_for('dashboard.home'))
    
    return render_template('report_error.html', request_id=request_id)