from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from supabase_client import supabase, is_admin, get_all_students, get_all_subjects, get_all_questions, toggle_admin

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
    # Get counts
    try:
        users_count = len(supabase.table('students').select('id', count='exact').execute().data)
        groups_count = len(supabase.table('groups').select('id', count='exact').execute().data)
        pdfs_count = len(supabase.table('pdfs').select('id', count='exact').execute().data)
        subjects_count = len(supabase.table('subjects').select('id', count='exact').execute().data)
        questions_count = len(supabase.table('questions').select('id', count='exact').execute().data)
        quiz_attempts = len(supabase.table('quiz_attempts').select('id', count='exact').execute().data)
    except Exception:
        users_count = groups_count = pdfs_count = subjects_count = questions_count = quiz_attempts = 0
    
    return render_template('dashboard/admin/dashboard.html',
                         users_count=users_count,
                         groups_count=groups_count,
                         pdfs_count=pdfs_count,
                         subjects_count=subjects_count,
                         questions_count=questions_count,
                         quiz_attempts=quiz_attempts)


# ============================================
# GROUPS ADMIN
# ============================================

@admin_bp.route('/groups')
@admin_required
def admin_groups():
    try:
        response = supabase.table('groups').select('*').order('created_at', desc=True).execute()
        groups = response.data if response.data else []
    except Exception:
        groups = []
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
    
    try:
        data = {
            'name': name,
            'platform': platform,
            'invite_link': invite_link,
            'description': description,
            'category': category if category else None,
            'is_active': True
        }
        supabase.table('groups').insert(data).execute()
        flash('Group added successfully!', 'success')
    except Exception as e:
        print(f"Error adding group: {e}")
        flash('Error adding group.', 'error')
    
    return redirect(url_for('admin.admin_groups'))


@admin_bp.route('/groups/delete/<group_id>', methods=['POST'])
@admin_required
def delete_group(group_id):
    try:
        supabase.table('groups').delete().eq('id', group_id).execute()
        flash('Group deleted successfully!', 'success')
    except Exception as e:
        print(f"Error deleting group: {e}")
        flash('Error deleting group.', 'error')
    return redirect(url_for('admin.admin_groups'))


# ============================================
# PDFS ADMIN
# ============================================

@admin_bp.route('/pdfs')
@admin_required
def admin_pdfs():
    try:
        response = supabase.table('pdfs').select('*').order('created_at', desc=True).execute()
        pdfs = response.data if response.data else []
    except Exception:
        pdfs = []
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
    
    try:
        data = {
            'title': title,
            'description': description,
            'file_url': file_url,
            'telegram_download_url': telegram_download_url,
            'subject': subject if subject else None,
            'grade': grade if grade else None,
            'category': category if category else None,
            'view_count': 0
        }
        supabase.table('pdfs').insert(data).execute()
        flash('PDF added successfully!', 'success')
    except Exception as e:
        print(f"Error adding PDF: {e}")
        flash('Error adding PDF.', 'error')
    
    return redirect(url_for('admin.admin_pdfs'))


@admin_bp.route('/pdfs/delete/<pdf_id>', methods=['POST'])
@admin_required
def delete_pdf(pdf_id):
    try:
        supabase.table('pdfs').delete().eq('id', pdf_id).execute()
        flash('PDF deleted successfully!', 'success')
    except Exception as e:
        print(f"Error deleting PDF: {e}")
        flash('Error deleting PDF.', 'error')
    return redirect(url_for('admin.admin_pdfs'))


# ============================================
# SUBJECTS ADMIN
# ============================================

@admin_bp.route('/subjects')
@admin_required
def admin_subjects():
    try:
        response = supabase.table('subjects').select('*').order('name').execute()
        subjects = response.data if response.data else []
    except Exception:
        subjects = []
    return render_template('dashboard/admin/subjects.html', subjects=subjects)


@admin_bp.route('/subjects/add', methods=['POST'])
@admin_required
def add_subject():
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '').strip()
    
    if not name:
        flash('Subject name is required.', 'error')
        return redirect(url_for('admin.admin_subjects'))
    
    try:
        data = {'name': name, 'icon': icon if icon else None}
        supabase.table('subjects').insert(data).execute()
        flash('Subject added successfully!', 'success')
    except Exception as e:
        print(f"Error adding subject: {e}")
        flash('Error adding subject. Name may already exist.', 'error')
    
    return redirect(url_for('admin.admin_subjects'))


@admin_bp.route('/subjects/delete/<subject_id>', methods=['POST'])
@admin_required
def delete_subject(subject_id):
    try:
        supabase.table('subjects').delete().eq('id', subject_id).execute()
        flash('Subject deleted successfully!', 'success')
    except Exception as e:
        print(f"Error deleting subject: {e}")
        flash('Error deleting subject. It may have questions linked.', 'error')
    return redirect(url_for('admin.admin_subjects'))


# ============================================
# QUESTIONS ADMIN
# ============================================

@admin_bp.route('/questions')
@admin_required
def admin_questions():
    try:
        response = supabase.table('questions')\
            .select('*, subjects(name)')\
            .order('created_at', desc=True)\
            .execute()
        questions = response.data if response.data else []
    except Exception:
        questions = []
    
    # Get subjects for dropdown
    try:
        subjects_response = supabase.table('subjects').select('id, name').order('name').execute()
        subjects = subjects_response.data if subjects_response.data else []
    except Exception:
        subjects = []
    
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
    
    try:
        data = {
            'subject_id': subject_id,
            'question_text': question_text,
            'options': {'A': option_a, 'B': option_b, 'C': option_c},
            'correct_answer': correct_answer,
            'difficulty': int(difficulty) if difficulty else 1,
            'explanation': explanation if explanation else None
        }
        supabase.table('questions').insert(data).execute()
        flash('Question added successfully!', 'success')
    except Exception as e:
        print(f"Error adding question: {e}")
        flash('Error adding question.', 'error')
    
    return redirect(url_for('admin.admin_questions'))


@admin_bp.route('/questions/edit/<question_id>', methods=['POST'])
@admin_required
def edit_question(question_id):
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
    
    try:
        data = {
            'subject_id': subject_id,
            'question_text': question_text,
            'options': {'A': option_a, 'B': option_b, 'C': option_c},
            'correct_answer': correct_answer,
            'difficulty': int(difficulty) if difficulty else 1,
            'explanation': explanation if explanation else None
        }
        supabase.table('questions').update(data).eq('id', question_id).execute()
        flash('Question updated successfully!', 'success')
    except Exception as e:
        print(f"Error updating question: {e}")
        flash('Error updating question.', 'error')
    
    return redirect(url_for('admin.admin_questions'))


@admin_bp.route('/questions/delete/<question_id>', methods=['POST'])
@admin_required
def delete_question(question_id):
    try:
        supabase.table('questions').delete().eq('id', question_id).execute()
        flash('Question deleted successfully!', 'success')
    except Exception as e:
        print(f"Error deleting question: {e}")
        flash('Error deleting question.', 'error')
    return redirect(url_for('admin.admin_questions'))


# ============================================
# USERS ADMIN
# ============================================

@admin_bp.route('/users')
@admin_required
def admin_users():
    try:
        users = get_all_students()
    except Exception:
        users = []
    return render_template('dashboard/admin/users.html', users=users)


@admin_bp.route('/users/toggle_admin/<user_id>', methods=['POST'])
@admin_required
def toggle_user_admin(user_id):
    if user_id == session['user_id']:
        flash('You cannot change your own admin status.', 'error')
        return redirect(url_for('admin.admin_users'))
    
    try:
        result = toggle_admin(user_id)
        if result:
            flash('Admin status updated successfully!', 'success')
        else:
            flash('Error updating admin status.', 'error')
    except Exception as e:
        print(f"Error toggling admin: {e}")
        flash('Error updating admin status.', 'error')
    
    return redirect(url_for('admin.admin_users'))