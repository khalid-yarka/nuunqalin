# blueprints/pdf_admin_bp.py
# Standalone PDF Admin Panel – Uses bot.db for pending operations

import os
import logging
import tempfile
import shutil
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, abort, send_file
from functools import wraps
from config import Config
from db import execute_with_retry, move_pending_to_pdfs
from subjects_config import get_all_subjects, get_subject
from bot.utils import get_bot
from bot.db import (
    get_pending_pdf_by_id, get_pending_pdf_list, count_pending_pdfs,
    delete_pending_pdf
)

logger = logging.getLogger(__name__)

# Blueprint
pdf_admin_bp = Blueprint('pdf_admin', __name__, url_prefix='/pdf-admin')

# Auth config - plain password
ADMIN_USERNAME = os.getenv('PDF_ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('PDF_ADMIN_PASSWORD', 'admin')
SESSION_KEY = 'pdf_admin_logged_in'
USERNAME_KEY = 'pdf_admin_username'
SESSION_TIMEOUT = int(os.getenv('PDF_ADMIN_SESSION_TIMEOUT', '1800'))

if ADMIN_PASSWORD == 'admin':
    logger.warning("PDF_ADMIN_PASSWORD is set to default 'admin'. Change it in .env for security.")

# ============================================
# DECORATORS
# ============================================

def pdf_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get(SESSION_KEY):
            flash('Please log in to access the PDF admin panel.', 'error')
            return redirect(url_for('pdf_admin.login'))
        if session.get('pdf_admin_login_time'):
            import time
            if time.time() - session['pdf_admin_login_time'] > SESSION_TIMEOUT:
                session.clear()
                flash('Session expired. Please log in again.', 'error')
                return redirect(url_for('pdf_admin.login'))
        return f(*args, **kwargs)
    return decorated

# ============================================
# ROUTES
# ============================================

@pdf_admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get(SESSION_KEY):
        return redirect(url_for('pdf_admin.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session[SESSION_KEY] = True
            session[USERNAME_KEY] = username
            session['pdf_admin_login_time'] = int(__import__('time').time())
            flash('Login successful.', 'success')
            logger.info(f"PDF Admin login successful for {username}")
            return redirect(url_for('pdf_admin.dashboard'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('pdf_admin/login.html')


@pdf_admin_bp.route('/logout')
def logout():
    session.pop(SESSION_KEY, None)
    session.pop(USERNAME_KEY, None)
    session.pop('pdf_admin_login_time', None)
    flash('Logged out.', 'info')
    return redirect(url_for('pdf_admin.login'))


@pdf_admin_bp.route('/')
@pdf_admin_required
def dashboard():
    pending_count = 0
    processed_count = 0
    today_uploads = 0
    today_processed = 0
    pending_list = []

    try:
        pending_count = count_pending_pdfs()
    except Exception as e:
        logger.error(f"Error counting pending PDFs: {e}")

    try:
        cursor = execute_with_retry("SELECT COUNT(*) as count FROM pdfs")
        processed_count = cursor.fetchone()['count'] if cursor.fetchone() else 0
    except Exception as e:
        logger.error(f"Error counting pdfs: {e}")

    try:
        cursor = execute_with_retry(
            "SELECT COUNT(*) as count FROM pending_pdfs WHERE date(uploaded_at) = date('now', 'localtime')"
        )
        today_uploads = cursor.fetchone()['count'] if cursor.fetchone() else 0
    except Exception as e:
        logger.error(f"Error counting today's uploads: {e}")

    try:
        cursor = execute_with_retry(
            "SELECT COUNT(*) as count FROM pdfs WHERE date(created_at) = date('now', 'localtime')"
        )
        today_processed = cursor.fetchone()['count'] if cursor.fetchone() else 0
    except Exception as e:
        logger.error(f"Error counting today's processed: {e}")

    try:
        pending_list = get_pending_pdf_list(limit=10)
    except Exception as e:
        logger.error(f"Error fetching pending list: {e}")

    return render_template('pdf_admin/dashboard.html',
                           pending_count=pending_count,
                           processed_count=processed_count,
                           today_uploads=today_uploads,
                           today_processed=today_processed,
                           pending_list=pending_list)


@pdf_admin_bp.route('/pending')
@pdf_admin_required
def pending_list():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    pending_list = []
    total = 0
    try:
        pending_list = get_pending_pdf_list(limit=per_page, offset=offset)
        total = count_pending_pdfs()
    except Exception as e:
        logger.error(f"Error in pending_list: {e}")
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    return render_template('pdf_admin/pending_list.html',
                           pending_list=pending_list,
                           page=page,
                           total_pages=total_pages)


@pdf_admin_bp.route('/pending/<int:pending_id>/process', methods=['GET', 'POST'])
@pdf_admin_required
def process_pending(pending_id):
    pending = None
    try:
        pending = get_pending_pdf_by_id(pending_id)
    except Exception as e:
        logger.error(f"Error fetching pending {pending_id}: {e}")
        flash('Database error.', 'error')
        return redirect(url_for('pdf_admin.pending_list'))

    if not pending:
        flash('Pending PDF not found.', 'error')
        return redirect(url_for('pdf_admin.pending_list'))

    subjects = get_all_subjects()

    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'description': request.form.get('description', '').strip(),
            'subject': request.form.get('subject', '').strip(),
            'grade': request.form.get('grade', '').strip(),
            'category': request.form.get('category', '').strip(),
            'chapters': request.form.get('chapters', '').strip(),
            'tags': request.form.get('tags', '').strip(),
            'is_premium': 1 if request.form.get('is_premium') == '1' else 0,
        }
        if not data['title'] or not data['subject'] or not data['grade']:
            flash('Title, Subject, and Grade are required.', 'error')
            return render_template('pdf_admin/process.html', pending=pending, subjects=subjects, data=data)

        session['pdf_review_data'] = data
        return redirect(url_for('pdf_admin.review_pending', pending_id=pending_id))

    return render_template('pdf_admin/process.html', pending=pending, subjects=subjects, data={})


@pdf_admin_bp.route('/pending/<int:pending_id>/review')
@pdf_admin_required
def review_pending(pending_id):
    pending = None
    try:
        pending = get_pending_pdf_by_id(pending_id)
    except Exception as e:
        logger.error(f"Error fetching pending {pending_id}: {e}")
        flash('Database error.', 'error')
        return redirect(url_for('pdf_admin.pending_list'))

    if not pending:
        flash('Pending PDF not found.', 'error')
        return redirect(url_for('pdf_admin.pending_list'))

    data = session.get('pdf_review_data')
    if not data:
        flash('No data to review. Please fill the form first.', 'error')
        return redirect(url_for('pdf_admin.process_pending', pending_id=pending_id))

    subject_obj = get_subject(data['subject'])
    data['subject_name'] = subject_obj['name'] if subject_obj else data['subject']

    return render_template('pdf_admin/review.html', pending=pending, data=data)


@pdf_admin_bp.route('/pending/<int:pending_id>/save', methods=['POST'])
@pdf_admin_required
def save_pending(pending_id):
    pending = None
    try:
        pending = get_pending_pdf_by_id(pending_id)
    except Exception as e:
        logger.error(f"Error fetching pending {pending_id}: {e}")
        flash('Database error.', 'error')
        return redirect(url_for('pdf_admin.pending_list'))

    if not pending:
        flash('Pending PDF not found.', 'error')
        return redirect(url_for('pdf_admin.pending_list'))

    data = {
        'title': request.form.get('title', '').strip(),
        'description': request.form.get('description', '').strip(),
        'subject': request.form.get('subject', '').strip(),
        'grade': request.form.get('grade', '').strip(),
        'category': request.form.get('category', '').strip(),
        'chapters': request.form.get('chapters', '').strip(),
        'tags': request.form.get('tags', '').strip(),
        'is_premium': 1 if request.form.get('is_premium') == '1' else 0,
        'file_unique_id': pending['file_unique_id'],
    }

    if not data['title'] or not data['subject'] or not data['grade']:
        flash('Missing required fields.', 'error')
        return redirect(url_for('pdf_admin.process_pending', pending_id=pending_id))

    try:
        bot = get_bot()
        file_info = bot.get_file(pending['file_id'])
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_path = temp_file.name
        temp_file.close()
        downloaded_file = bot.download_file(file_info.file_path)
        with open(temp_path, 'wb') as f:
            f.write(downloaded_file)

        upload_folder = Config.UPLOAD_FOLDER
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder, exist_ok=True)
        safe_filename = f"{pending['id']}_{pending['filename'].replace(' ', '_')}"
        dest_path = os.path.join(upload_folder, safe_filename)
        shutil.move(temp_path, dest_path)
        file_url_local = f"/static/uploads/pdfs/{safe_filename}"
        telegram_download_url = file_url_local

        pdf_data = {
            'title': data['title'],
            'description': data['description'],
            'subject': data['subject'],
            'grade': data['grade'],
            'category': data['category'],
            'chapters': data['chapters'],
            'tags': data['tags'],
            'is_premium': data['is_premium'],
            'file_url': file_url_local,
            'telegram_download_url': telegram_download_url,
            'file_unique_id': pending['file_unique_id'],
        }
        success, result = move_pending_to_pdfs(pending_id, pdf_data)
        if success:
            flash(f'PDF successfully published! (ID: {result})', 'success')
            session.pop('pdf_review_data', None)
            return redirect(url_for('pdf_admin.dashboard'))
        else:
            flash(f'Failed to save PDF: {result}', 'error')
            return redirect(url_for('pdf_admin.process_pending', pending_id=pending_id))
    except Exception as e:
        logger.error(f"Error saving pending PDF: {e}", exc_info=True)
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('pdf_admin.process_pending', pending_id=pending_id))


@pdf_admin_bp.route('/pending/<int:pending_id>/preview')
@pdf_admin_required
def preview_pdf(pending_id):
    pending = None
    try:
        pending = get_pending_pdf_by_id(pending_id)
    except Exception as e:
        logger.error(f"Error fetching pending {pending_id}: {e}")
        abort(500)

    if not pending:
        abort(404)

    try:
        bot = get_bot()
        file_info = bot.get_file(pending['file_id'])
        downloaded = bot.download_file(file_info.file_path)
        return send_file(
            downloaded,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=pending['filename']
        )
    except Exception as e:
        logger.error(f"Preview error: {e}")
        abort(500)