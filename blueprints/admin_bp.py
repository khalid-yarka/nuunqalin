from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify, abort
from db import (
    is_admin, get_all_students, get_all_questions,
    toggle_admin, delete_user as db_delete_user, get_deleted_users,
    restore_deleted_user as db_restore_user, create_subject, delete_subject,
    create_question, delete_question, create_group, delete_group,
    create_pdf, delete_pdf, get_all_groups, get_all_pdfs,
    get_subject_by_name, bulk_create_questions, check_question_exists,
    create_notification_for_all_users,
    execute_with_retry,
    get_user_subject_list  # for subject validation if needed
)
from error_models import get_error_stats
from functools import wraps
import json
import secrets

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ============================================
# DECORATORS
# ============================================

def admin_required(f):
    """Decorator to require admin access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'error')
            return redirect(url_for('login'))
        if not is_admin(session['user_id']):
            flash('Access denied. Admin only.', 'error')
            return redirect(url_for('dashboard.home'))
        return f(*args, **kwargs)
    return decorated_function


def validate_csrf():
    """Validate CSRF token from form or header; aborts on failure."""
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or token != session.get('csrf_token'):
        abort(403, 'CSRF token validation failed')


# ============================================
# ADMIN DASHBOARD
# ============================================

@admin_bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard with stats, activity feed, and backup health."""
    users = get_all_students()
    groups = get_all_groups()
    pdfs = get_all_pdfs()
    questions = get_all_questions()
    error_stats = get_error_stats()

    # Get backup health
    try:
        from backup import BackupManager
        manager = BackupManager()
        backup_health = manager.get_backup_health_summary()
    except Exception as e:
        backup_health = {'status': 'error', 'issues': [str(e)]}

    # Get recent activity (last 10)
    try:
        cursor = execute_with_retry(
            "SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 10"
        )
        recent_activity = [dict(row) for row in cursor.fetchall()]
    except Exception:
        recent_activity = []

    return render_template('dashboard/admin/dashboard.html',
                         users_count=len(users),
                         groups_count=len(groups),
                         pdfs_count=len(pdfs),
                         subjects_count=0,  # removed
                         questions_count=len(questions),
                         quiz_attempts=0,
                         error_stats=error_stats,
                         backup_health=backup_health,
                         recent_activity=recent_activity)


# ============================================
# BULK IMPORT QUESTIONS – UPDATED WITH subject_code
# ============================================

@admin_bp.route('/bulk-import', methods=['GET', 'POST'])
@admin_required
def bulk_import():
    """Bulk import questions via JSON."""
    # Get all subject codes from config for validation
    from subjects_config import get_all_subject_codes, get_subject
    all_subject_codes = get_all_subject_codes()

    if request.method == 'POST':
        validate_csrf()

        json_data = request.form.get('json_data', '').strip()
        file_data = request.files.get('json_file')

        if file_data and file_data.filename:
            try:
                content = file_data.read().decode('utf-8')
                data = json.loads(content)
            except Exception as e:
                flash(f'Error reading file: {str(e)}', 'error')
                return render_template('dashboard/admin/bulk_import.html')
        elif json_data:
            try:
                data = json.loads(json_data)
            except json.JSONDecodeError as e:
                flash(f'Invalid JSON format: {str(e)}', 'error')
                return render_template('dashboard/admin/bulk_import.html')
        else:
            flash('Please paste JSON or upload a file.', 'error')
            return render_template('dashboard/admin/bulk_import.html')

        if 'metadata' not in data:
            flash('Missing "metadata" section in JSON.', 'error')
            return render_template('dashboard/admin/bulk_import.html')

        if 'questions' not in data or not data['questions']:
            flash('Missing or empty "questions" array in JSON.', 'error')
            return render_template('dashboard/admin/bulk_import.html')

        subject_code = data['metadata'].get('subject_code', '').strip()
        if not subject_code:
            flash('subject_code is required in metadata.', 'error')
            return render_template('dashboard/admin/bulk_import.html')

        # Validate subject_code exists in config
        if subject_code not in all_subject_codes:
            available = ', '.join(all_subject_codes)
            flash(f'Subject code "{subject_code}" not found. Available: {available}', 'error')
            return render_template('dashboard/admin/bulk_import.html')

        chapter = data['metadata'].get('chapter', '').strip()

        questions_to_import = []
        errors = []
        duplicates = []

        for idx, q in enumerate(data['questions'], 1):
            if not q.get('question', '').strip():
                errors.append({'index': idx, 'question': 'Unknown', 'error': 'Question text is required'})
                continue

            if not q.get('options') or len(q['options']) < 3:
                errors.append({'index': idx, 'question': q.get('question', 'Unknown'), 'error': 'Minimum 3 options required'})
                continue

            if len(q['options']) > 6:
                errors.append({'index': idx, 'question': q.get('question', 'Unknown'), 'error': 'Maximum 6 options allowed'})
                continue

            if not q.get('correct') or q['correct'] < 1 or q['correct'] > len(q['options']):
                errors.append({'index': idx, 'question': q.get('question', 'Unknown'), 'error': 'Invalid correct answer index'})
                continue

            difficulty = q.get('difficulty', 1)
            if difficulty < 1 or difficulty > 5:
                errors.append({'index': idx, 'question': q.get('question', 'Unknown'), 'error': 'Difficulty must be 1-5'})
                continue

            question_text = q['question'].strip()
            if check_question_exists(question_text, subject_code):
                duplicates.append({'index': idx, 'question': question_text, 'error': 'Duplicate question'})
                continue

            options_dict = {}
            option_labels = ['A', 'B', 'C', 'D', 'E', 'F']
            for i, opt in enumerate(q['options']):
                if i < len(option_labels):
                    options_dict[option_labels[i]] = opt.strip()

            correct_letter = option_labels[q['correct'] - 1]

            question_data = {
                'subject_code': subject_code,
                'question_text': question_text,
                'options': options_dict,
                'correct_answer': correct_letter,
                'difficulty': difficulty,
                'chapter': chapter,
                'tags': ','.join(q.get('tags', [])),
                'explanation': q.get('explanation', '').strip(),
                'created_by': session['user_id'],
                'updated_by': session['user_id']
            }
            questions_to_import.append(question_data)

        if errors or duplicates:
            return render_template('dashboard/admin/bulk_import.html',
                                 preview=True,
                                 valid_questions=questions_to_import,
                                 errors=errors,
                                 duplicates=duplicates,
                                 subject_code=subject_code,
                                 chapter=chapter,
                                 total_questions=len(data['questions']))

        if questions_to_import:
            result = bulk_create_questions(questions_to_import, session['user_id'])
            if result['imported'] > 0:
                flash(f'✅ {result["imported"]} questions imported successfully!', 'success')
            if result['errors']:
                flash(f'⚠️ {len(result["errors"])} questions failed to import.', 'error')
            return redirect(url_for('admin.admin_questions'))
        else:
            flash('No valid questions to import.', 'error')

    return render_template('dashboard/admin/bulk_import.html')


@admin_bp.route('/bulk-preview', methods=['POST'])
@admin_required
def bulk_preview():
    """Preview questions before import."""
    from subjects_config import get_all_subject_codes
    all_subject_codes = get_all_subject_codes()

    json_data = request.form.get('json_data', '').strip()
    if not json_data:
        return jsonify({'error': 'No JSON data provided'}), 400

    try:
        data = json.loads(json_data)
    except json.JSONDecodeError as e:
        return jsonify({'error': f'Invalid JSON: {str(e)}'}), 400

    if 'metadata' not in data:
        return jsonify({'error': 'Missing metadata section'}), 400

    if 'questions' not in data or not data['questions']:
        return jsonify({'error': 'Missing or empty questions array'}), 400

    subject_code = data['metadata'].get('subject_code', '').strip()
    if not subject_code:
        return jsonify({'error': 'subject_code is required'}), 400

    if subject_code not in all_subject_codes:
        return jsonify({'error': f'Subject code "{subject_code}" not found.'}), 400

    preview = []
    for idx, q in enumerate(data['questions'], 1):
        preview.append({
            'index': idx,
            'question': q.get('question', '')[:50] + ('...' if len(q.get('question', '')) > 50 else ''),
            'difficulty': q.get('difficulty', 1),
            'options_count': len(q.get('options', [])),
            'has_explanation': bool(q.get('explanation', '').strip()),
            'tags': ', '.join(q.get('tags', []))[:30]
        })

    return jsonify({
        'subject_code': subject_code,
        'chapter': data['metadata'].get('chapter', ''),
        'total': len(data['questions']),
        'preview': preview[:10]
    })


@admin_bp.route('/bulk-template')
@admin_required
def bulk_template():
    """Download template JSON file."""
    template = {
        "metadata": {
            "subject_code": "geography",
            "chapter": "Chapter 1: Introduction"
        },
        "questions": [
            {
                "tags": ["geography", "africa", "capitals"],
                "difficulty": 2,
                "question": "What is the capital of Somalia?",
                "options": ["Mogadishu", "Hargeisa", "Kismayo", "Garowe"],
                "correct": 1,
                "explanation": "Mogadishu has been the capital since 1960."
            },
            {
                "tags": ["geography", "africa", "rivers"],
                "difficulty": 3,
                "question": "Which is the longest river in Africa?",
                "options": ["Nile", "Congo", "Niger", "Zambezi"],
                "correct": 1,
                "explanation": "The Nile is approximately 6,650 km long."
            }
        ]
    }

    response = jsonify(template)
    response.headers['Content-Disposition'] = 'attachment; filename=bulk_import_template.json'
    response.headers['Content-Type'] = 'application/json'
    return response


# ============================================
# DELETE USER (unchanged)
# ============================================

@admin_bp.route('/users/delete/<user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    """Delete a user permanently with options."""
    validate_csrf()

    if user_id == session['user_id']:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin.admin_users'))

    keep_ratings = request.form.get('keep_ratings') == 'on'
    delete_attempts = request.form.get('delete_attempts') == 'on'

    success, message = db_delete_user(user_id, session['user_id'], keep_ratings, delete_attempts)

    if success:
        flash('User deleted successfully!', 'success')
    else:
        flash(f'Error deleting user: {message}', 'error')

    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/deleted-users')
@admin_required
def deleted_users():
    """View deleted users (recovery)."""
    deleted = get_deleted_users()
    return render_template('dashboard/admin/deleted_users.html', deleted=deleted)


@admin_bp.route('/deleted-users/restore/<deleted_id>', methods=['POST'])
@admin_required
def restore_deleted_user(deleted_id):
    """Restore a deleted user."""
    validate_csrf()
    success, message = db_restore_user(deleted_id)
    if success:
        flash('User restored successfully!', 'success')
    else:
        flash(f'Error restoring user: {message}', 'error')
    return redirect(url_for('admin.deleted_users'))


# ============================================
# GROUPS ADMIN (unchanged)
# ============================================

@admin_bp.route('/groups')
@admin_required
def admin_groups():
    groups = get_all_groups()
    return render_template('dashboard/admin/groups.html', groups=groups)


@admin_bp.route('/groups/add', methods=['POST'])
@admin_required
def add_group():
    validate_csrf()
    name = request.form.get('name', '').strip()
    platform = request.form.get('platform', '')
    invite_link = request.form.get('invite_link', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip()

    if not name or not platform or not invite_link:
        flash('Name, platform, and invite link are required.', 'error')
        return redirect(url_for('admin.admin_groups'))

    data = {
        'name': name,
        'platform': platform,
        'invite_link': invite_link,
        'description': description,
        'category': category if category else ''
    }

    if create_group(data):
        flash('Group added successfully!', 'success')
    else:
        flash('Error adding group.', 'error')
    return redirect(url_for('admin.admin_groups'))


@admin_bp.route('/groups/delete/<group_id>', methods=['POST'])
@admin_required
def delete_group(group_id):
    validate_csrf()
    if delete_group(group_id):
        flash('Group deleted successfully!', 'success')
    else:
        flash('Error deleting group.', 'error')
    return redirect(url_for('admin.admin_groups'))


# ============================================
# PDFS ADMIN (unchanged)
# ============================================

@admin_bp.route('/pdfs')
@admin_required
def admin_pdfs():
    pdfs = get_all_pdfs()
    return render_template('dashboard/admin/pdfs.html', pdfs=pdfs)


@admin_bp.route('/pdfs/add', methods=['POST'])
@admin_required
def add_pdf():
    validate_csrf()
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    file_url = request.form.get('file_url', '').strip()
    telegram_download_url = request.form.get('telegram_download_url', '').strip()
    subject = request.form.get('subject', '').strip()
    grade = request.form.get('grade', '').strip()
    category = request.form.get('category', '').strip()

    if not title or not file_url or not telegram_download_url:
        flash('Title, file URL, and Telegram download URL are required.', 'error')
        return redirect(url_for('admin.admin_pdfs'))

    data = {
        'title': title,
        'description': description,
        'file_url': file_url,
        'telegram_download_url': telegram_download_url,
        'subject': subject if subject else '',
        'grade': grade if grade else '',
        'category': category if category else '',
        'view_count': 0
    }

    if create_pdf(data):
        flash('PDF added successfully!', 'success')
    else:
        flash('Error adding PDF.', 'error')
    return redirect(url_for('admin.admin_pdfs'))


@admin_bp.route('/pdfs/delete/<pdf_id>', methods=['POST'])
@admin_required
def delete_pdf(pdf_id):
    validate_csrf()
    if delete_pdf(pdf_id):
        flash('PDF deleted successfully!', 'success')
    else:
        flash('Error deleting PDF.', 'error')
    return redirect(url_for('admin.admin_pdfs'))


# ============================================
# QUESTIONS ADMIN (Single Entry)
# ============================================

@admin_bp.route('/questions')
@admin_required
def admin_questions():
    questions = get_all_questions()
    # For subject list, we need all subject codes from config for the dropdown
    from subjects_config import get_all_subjects
    subjects = get_all_subjects()
    return render_template('dashboard/admin/questions.html', questions=questions, subjects=subjects)


@admin_bp.route('/questions/add', methods=['POST'])
@admin_required
def add_question():
    validate_csrf()
    subject_code = request.form.get('subject_code', '').strip()
    question_text = request.form.get('question_text', '').strip()
    option_a = request.form.get('option_a', '').strip()
    option_b = request.form.get('option_b', '').strip()
    option_c = request.form.get('option_c', '').strip()
    option_d = request.form.get('option_d', '').strip()
    option_e = request.form.get('option_e', '').strip()
    correct_answer = request.form.get('correct_answer', '')
    difficulty = request.form.get('difficulty', 1)
    chapter = request.form.get('chapter', '').strip()
    tags = request.form.get('tags', '').strip()
    explanation = request.form.get('explanation', '').strip()

    if not subject_code or not question_text or not option_a or not option_b or not option_c or not correct_answer:
        flash('Subject, question, options A-C, and correct answer are required.', 'error')
        return redirect(url_for('admin.admin_questions'))

    # Validate subject_code exists
    from subjects_config import get_subject
    if not get_subject(subject_code):
        flash('Invalid subject code.', 'error')
        return redirect(url_for('admin.admin_questions'))

    options = {'A': option_a, 'B': option_b, 'C': option_c}
    if option_d:
        options['D'] = option_d
    if option_e:
        options['E'] = option_e

    data = {
        'subject_code': subject_code,
        'question_text': question_text,
        'options': options,
        'correct_answer': correct_answer,
        'difficulty': int(difficulty) if difficulty else 1,
        'chapter': chapter,
        'tags': tags,
        'explanation': explanation,
        'created_by': session['user_id'],
        'updated_by': session['user_id']
    }

    if create_question(data):
        flash('Question added successfully!', 'success')
    else:
        flash('Error adding question.', 'error')
    return redirect(url_for('admin.admin_questions'))


@admin_bp.route('/questions/delete/<question_id>', methods=['POST'])
@admin_required
def delete_question(question_id):
    validate_csrf()
    if delete_question(question_id):
        flash('Question archived successfully!', 'success')
    else:
        flash('Error archiving question.', 'error')
    return redirect(url_for('admin.admin_questions'))


# ============================================
# USERS ADMIN (unchanged)
# ============================================

@admin_bp.route('/users')
@admin_required
def admin_users():
    users = get_all_students()
    return render_template('dashboard/admin/users.html', users=users)


@admin_bp.route('/users/toggle_admin/<user_id>', methods=['POST'])
@admin_required
def toggle_user_admin(user_id):
    validate_csrf()
    if user_id == session['user_id']:
        flash('You cannot change your own admin status.', 'error')
        return redirect(url_for('admin.admin_users'))

    result = toggle_admin(user_id)
    if result:
        flash('Admin status updated successfully!', 'success')
    else:
        flash('Error updating admin status.', 'error')
    return redirect(url_for('admin.admin_users'))


# ============================================
# ADMIN ANNOUNCEMENT (unchanged)
# ============================================

@admin_bp.route('/announcement', methods=['GET', 'POST'])
@admin_required
def admin_announcement():
    """Admin page to send announcements to all users."""
    if request.method == 'POST':
        validate_csrf()
        title = request.form.get('title', '').strip()
        body = request.form.get('body', '').strip()
        link = request.form.get('link', '').strip()

        if not title or not body:
            flash('Title and body are required.', 'error')
            return render_template('dashboard/admin/announcement.html')

        create_notification_for_all_users(
            type='admin',
            title=title,
            body=body,
            link=link or '/dashboard',
            icon='📢'
        )

        flash('✅ Announcement sent to all users!', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('dashboard/admin/announcement.html')