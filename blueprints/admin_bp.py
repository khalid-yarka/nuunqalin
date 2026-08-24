from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from db import (
    is_admin, get_all_students, get_all_subjects, get_all_questions,
    toggle_admin, delete_user as db_delete_user, get_deleted_users,
    restore_deleted_user as db_restore_user, create_subject, delete_subject,
    create_question, delete_question, create_group, delete_group,
    create_pdf, delete_pdf, get_all_groups, get_all_pdfs
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    """Decorator to require admin access"""
    from functools import wraps
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

# ============================================
# ADMIN DASHBOARD
# ============================================

@admin_bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard"""
    users = get_all_students()
    groups = get_all_groups()
    pdfs = get_all_pdfs()
    subjects = get_all_subjects()
    questions = get_all_questions()
    
    return render_template('dashboard/admin/dashboard.html',
                         users_count=len(users),
                         groups_count=len(groups),
                         pdfs_count=len(pdfs),
                         subjects_count=len(subjects),
                         questions_count=len(questions),
                         quiz_attempts=0)  # You can add a count query if needed

# ============================================
# DELETE USER
# ============================================

@admin_bp.route('/users/delete/<user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    """Delete a user permanently with options"""
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
    """View deleted users (recovery)"""
    deleted = get_deleted_users()
    return render_template('dashboard/admin/deleted_users.html', deleted=deleted)

@admin_bp.route('/deleted-users/restore/<deleted_id>', methods=['POST'])
@admin_required
def restore_deleted_user(deleted_id):
    """Restore a deleted user"""
    success, message = db_restore_user(deleted_id)
    
    if success:
        flash('User restored successfully!', 'success')
    else:
        flash(f'Error restoring user: {message}', 'error')
    
    return redirect(url_for('admin.deleted_users'))

# ============================================
# GROUPS ADMIN
# ============================================

@admin_bp.route('/groups')
@admin_required
def admin_groups():
    groups = get_all_groups()
    return render_template('dashboard/admin/groups.html', groups=groups)

@admin_bp.route('/groups/add', methods=['POST'])
@admin_required
def add_group():
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
    if delete_group(group_id):
        flash('Group deleted successfully!', 'success')
    else:
        flash('Error deleting group.', 'error')
    return redirect(url_for('admin.admin_groups'))

# ============================================
# PDFS ADMIN
# ============================================

@admin_bp.route('/pdfs')
@admin_required
def admin_pdfs():
    pdfs = get_all_pdfs()
    return render_template('dashboard/admin/pdfs.html', pdfs=pdfs)

@admin_bp.route('/pdfs/add', methods=['POST'])
@admin_required
def add_pdf():
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
    if delete_pdf(pdf_id):
        flash('PDF deleted successfully!', 'success')
    else:
        flash('Error deleting PDF.', 'error')
    return redirect(url_for('admin.admin_pdfs'))

# ============================================
# SUBJECTS ADMIN
# ============================================

@admin_bp.route('/subjects')
@admin_required
def admin_subjects():
    subjects = get_all_subjects()
    return render_template('dashboard/admin/subjects.html', subjects=subjects)

@admin_bp.route('/subjects/add', methods=['POST'])
@admin_required
def add_subject():
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '').strip()
    
    if not name:
        flash('Subject name is required.', 'error')
        return redirect(url_for('admin.admin_subjects'))
    
    data = {'name': name, 'icon': icon if icon else '📚'}
    if create_subject(data):
        flash('Subject added successfully!', 'success')
    else:
        flash('Error adding subject. Name may already exist.', 'error')
    
    return redirect(url_for('admin.admin_subjects'))

@admin_bp.route('/subjects/delete/<subject_id>', methods=['POST'])
@admin_required
def delete_subject(subject_id):
    if delete_subject(subject_id):
        flash('Subject deleted successfully!', 'success')
    else:
        flash('Error deleting subject. It may have questions linked.', 'error')
    return redirect(url_for('admin.admin_subjects'))

# ============================================
# QUESTIONS ADMIN
# ============================================

@admin_bp.route('/questions')
@admin_required
def admin_questions():
    questions = get_all_questions()
    subjects = get_all_subjects()
    return render_template('dashboard/admin/questions.html', questions=questions, subjects=subjects)

@admin_bp.route('/questions/add', methods=['POST'])
@admin_required
def add_question():
    subject_id = request.form.get('subject_id', '')
    question_text = request.form.get('question_text', '').strip()
    option_a = request.form.get('option_a', '').strip()
    option_b = request.form.get('option_b', '').strip()
    option_c = request.form.get('option_c', '').strip()
    correct_answer = request.form.get('correct_answer', '')
    difficulty = request.form.get('difficulty', 1)
    explanation = request.form.get('explanation', '').strip()
    
    if not subject_id or not question_text or not option_a or not option_b or not option_c or not correct_answer:
        flash('All fields except explanation are required.', 'error')
        return redirect(url_for('admin.admin_questions'))
    
    data = {
        'subject_id': subject_id,
        'question_text': question_text,
        'options': {'A': option_a, 'B': option_b, 'C': option_c},
        'correct_answer': correct_answer,
        'difficulty': int(difficulty) if difficulty else 1,
        'explanation': explanation if explanation else ''
    }
    
    if create_question(data):
        flash('Question added successfully!', 'success')
    else:
        flash('Error adding question.', 'error')
    
    return redirect(url_for('admin.admin_questions'))

@admin_bp.route('/questions/delete/<question_id>', methods=['POST'])
@admin_required
def delete_question(question_id):
    if delete_question(question_id):
        flash('Question deleted successfully!', 'success')
    else:
        flash('Error deleting question.', 'error')
    return redirect(url_for('admin.admin_questions'))

# ============================================
# USERS ADMIN
# ============================================

@admin_bp.route('/users')
@admin_required
def admin_users():
    users = get_all_students()
    return render_template('dashboard/admin/users.html', users=users)

@admin_bp.route('/users/toggle_admin/<user_id>', methods=['POST'])
@admin_required
def toggle_user_admin(user_id):
    if user_id == session['user_id']:
        flash('You cannot change your own admin status.', 'error')
        return redirect(url_for('admin.admin_users'))
    
    result = toggle_admin(user_id)
    if result:
        flash('Admin status updated successfully!', 'success')
    else:
        flash('Error updating admin status.', 'error')
    
    return redirect(url_for('admin.admin_users'))