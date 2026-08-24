import sqlite3
import json
import secrets
import string
from datetime import datetime, timezone, timedelta
from config import Config
from utils import get_somali_time, get_somali_time_db, format_somali_time

# ============================================
# DATABASE CONNECTION
# ============================================

DB_PATH = 'nuunplatform.db'

def get_db():
    """Get database connection with JSON serialization support"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

# ============================================
# JSON HELPERS
# ============================================

def to_json(data):
    return json.dumps(data) if data is not None else None

def from_json(data):
    return json.loads(data) if data else None

# ============================================
# TIME HELPERS
# ============================================

def now():
    """Get current time in Somali timezone as string"""
    return get_somali_time_db()

# ============================================
# PUBLIC ID GENERATION
# ============================================

PUBLIC_ID_CHARS = string.ascii_uppercase + '123456789'

def generate_public_id() -> str:
    """Generate a unique 4-character alphanumeric public ID"""
    return ''.join(secrets.choice(PUBLIC_ID_CHARS) for _ in range(4))

def get_student_by_public_id(public_id: str):
    """Get student by public ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE public_id = ?", (public_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

# ============================================
# STUDENT FUNCTIONS
# ============================================

def get_student_by_phone(phone: str):
    """Get student by phone number"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE phone_number = ?", (phone,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

def get_student_by_id(student_id: int):
    """Get student by internal ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

def create_student(data: dict):
    """Create a new student with auto-generated public_id"""
    try:
        public_id = generate_public_id()
        while get_student_by_public_id(public_id):
            public_id = generate_public_id()
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO students (
                public_id, phone_number, password, first_name,
                middle_name, last_name, location, city, school, grade,
                total_points, is_admin, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            public_id,
            data['phone_number'],
            data['password'],  # Plain text - NO HASHING
            data['first_name'],
            data.get('middle_name', ''),
            data['last_name'],
            data.get('location', ''),
            data.get('city', ''),
            data.get('school', ''),
            data.get('grade', ''),
            data.get('total_points', 0),
            0,
            now()  # Somali time
        ))
        conn.commit()
        conn.close()
        return get_student_by_phone(data['phone_number'])
    except Exception as e:
        print(f"Error creating student: {e}")
        return None

def update_student_points(student_id: int, points: int):
    """Update student's total points"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE students SET total_points = ? WHERE id = ?",
            (points, student_id)
        )
        conn.commit()
        conn.close()
        return get_student_by_id(student_id)
    except Exception as e:
        print(f"Error updating points: {e}")
        return None

def is_admin(user_id: int) -> bool:
    """Check if a user is an admin"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT is_admin FROM students WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return bool(result['is_admin']) if result else False
    except Exception as e:
        print(f"Error checking admin: {e}")
        return False

def toggle_admin(user_id: int):
    """Toggle admin status for a user"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT is_admin FROM students WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        if not result:
            conn.close()
            return None
        
        new_status = 0 if result['is_admin'] else 1
        cursor.execute(
            "UPDATE students SET is_admin = ? WHERE id = ?",
            (new_status, user_id)
        )
        conn.commit()
        conn.close()
        return get_student_by_id(user_id)
    except Exception as e:
        print(f"Error toggling admin: {e}")
        return None

def get_all_students():
    """Get all students (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, public_id, first_name, last_name, phone_number, 
                   location, school, grade, total_points, is_admin, created_at
            FROM students
            ORDER BY created_at DESC
        """)
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error fetching students: {e}")
        return []

def get_schools_by_location(location: str):
    """Get schools by location"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM schools WHERE location = ?", (location,))
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error fetching schools: {e}")
        return []

# ============================================
# SUBJECT FUNCTIONS
# ============================================

def get_all_subjects():
    """Get all subjects"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subjects ORDER BY name")
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error fetching subjects: {e}")
        return []

def get_subject_by_id(subject_id: int):
    """Get subject by ID"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        print(f"Error fetching subject: {e}")
        return None

def create_subject(data: dict):
    """Create a new subject"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subjects (name, icon)
            VALUES (?, ?)
        """, (data['name'], data.get('icon', '')))
        conn.commit()
        conn.close()
        return get_subject_by_name(data['name'])
    except Exception as e:
        print(f"Error creating subject: {e}")
        return None

def get_subject_by_name(name: str):
    """Get subject by name"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subjects WHERE name = ?", (name,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        print(f"Error fetching subject: {e}")
        return None

def delete_subject(subject_id: int):
    """Delete a subject"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting subject: {e}")
        return False

# ============================================
# QUESTION FUNCTIONS
# ============================================

def get_questions_by_subject(subject_id: int, limit: int = 10):
    """Get random questions for a subject"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, question_text, options, correct_answer, explanation
            FROM questions
            WHERE subject_id = ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (subject_id, limit))
        results = cursor.fetchall()
        conn.close()
        
        questions = []
        for row in results:
            q = dict(row)
            q['options'] = from_json(q['options'])
            questions.append(q)
        return questions
    except Exception as e:
        print(f"Error fetching questions: {e}")
        return []

def get_all_questions():
    """Get all questions with subject names (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.*, s.name as subject_name
            FROM questions q
            LEFT JOIN subjects s ON q.subject_id = s.id
            ORDER BY q.created_at DESC
        """)
        results = cursor.fetchall()
        conn.close()
        
        questions = []
        for row in results:
            q = dict(row)
            q['options'] = from_json(q['options'])
            q['subjects'] = {'name': q.pop('subject_name', '')} if q.get('subject_name') else None
            questions.append(q)
        return questions
    except Exception as e:
        print(f"Error fetching questions: {e}")
        return []

def create_question(data: dict):
    """Create a new question"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO questions (
                subject_id, question_text, options, correct_answer,
                difficulty, explanation, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data['subject_id'],
            data['question_text'],
            to_json(data['options']),
            data['correct_answer'],
            data.get('difficulty', 1),
            data.get('explanation', ''),
            now()
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error creating question: {e}")
        return False

def update_question(question_id: int, data: dict):
    """Update a question"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE questions SET
                subject_id = ?,
                question_text = ?,
                options = ?,
                correct_answer = ?,
                difficulty = ?,
                explanation = ?
            WHERE id = ?
        """, (
            data['subject_id'],
            data['question_text'],
            to_json(data['options']),
            data['correct_answer'],
            data.get('difficulty', 1),
            data.get('explanation', ''),
            question_id
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating question: {e}")
        return False

def delete_question(question_id: int):
    """Delete a question"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting question: {e}")
        return False

def get_question_by_id(question_id: int):
    """Get a question by ID"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            q = dict(result)
            q['options'] = from_json(q['options'])
            return q
        return None
    except Exception as e:
        print(f"Error fetching question: {e}")
        return None

# ============================================
# QUIZ ATTEMPT FUNCTIONS
# ============================================

def save_quiz_attempt(student_id: int, subject_id: int, score: int, total: int, answers: list, ratings: list):
    """Save a quiz attempt"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO quiz_attempts (
                student_id, subject_id, score, total_questions,
                answers, ratings, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            student_id,
            subject_id,
            score,
            total,
            to_json(answers),
            to_json(ratings),
            now()
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving quiz attempt: {e}")
        return None

def get_user_quiz_history(student_id: int, limit: int = 10):
    """Get user's quiz history"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT qa.*, s.name as subject_name
            FROM quiz_attempts qa
            LEFT JOIN subjects s ON qa.subject_id = s.id
            WHERE qa.student_id = ?
            ORDER BY qa.completed_at DESC
            LIMIT ?
        """, (student_id, limit))
        results = cursor.fetchall()
        conn.close()
        
        attempts = []
        for row in results:
            a = dict(row)
            a['subjects'] = {'name': a.pop('subject_name', '')} if a.get('subject_name') else None
            a['answers'] = from_json(a['answers'])
            a['ratings'] = from_json(a['ratings'])
            attempts.append(a)
        return attempts
    except Exception as e:
        print(f"Error fetching quiz history: {e}")
        return []

def get_leaderboard(limit: int = 20):
    """Get global leaderboard"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT public_id, first_name, last_name, total_points, school
            FROM students
            ORDER BY total_points DESC
            LIMIT ?
        """, (limit,))
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error fetching leaderboard: {e}")
        return []

# ============================================
# DELETED USERS FUNCTIONS
# ============================================

def delete_user(student_id: int, admin_id: int, keep_ratings: bool = True, delete_attempts: bool = True):
    """Delete a user and backup their data"""
    try:
        user = get_student_by_id(student_id)
        if not user:
            return None, 'User not found'
        
        if student_id == admin_id:
            return None, 'You cannot delete your own account'
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO deleted_users (
                original_id, public_id, first_name, last_name,
                phone_number, school, grade, total_points, is_admin,
                location, city, deleted_by, data, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user['id'],
            user.get('public_id'),
            user.get('first_name'),
            user.get('last_name'),
            user.get('phone_number'),
            user.get('school'),
            user.get('grade'),
            user.get('total_points', 0),
            user.get('is_admin', 0),
            user.get('location'),
            user.get('city'),
            admin_id,
            to_json(user),
            now()
        ))
        
        if delete_attempts:
            cursor.execute("DELETE FROM quiz_attempts WHERE student_id = ?", (student_id,))
        
        if not keep_ratings:
            cursor.execute("DELETE FROM quiz_ratings WHERE student_id = ?", (student_id,))
        
        cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
        
        conn.commit()
        conn.close()
        return True, 'User deleted successfully'
        
    except Exception as e:
        print(f"Error deleting user: {e}")
        return False, str(e)

def get_deleted_users(limit: int = 50):
    """Get list of deleted users for admin recovery"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.*, s.first_name as admin_first_name, s.last_name as admin_last_name, s.public_id as admin_public_id
            FROM deleted_users d
            LEFT JOIN students s ON d.deleted_by = s.id
            ORDER BY d.deleted_at DESC
            LIMIT ?
        """, (limit,))
        results = cursor.fetchall()
        conn.close()
        
        deleted = []
        for row in results:
            d = dict(row)
            d['deleted_by_data'] = {
                'first_name': d.pop('admin_first_name', ''),
                'last_name': d.pop('admin_last_name', ''),
                'public_id': d.pop('admin_public_id', '')
            } if d.get('admin_first_name') else None
            d['data'] = from_json(d['data'])
            deleted.append(d)
        return deleted
    except Exception as e:
        print(f"Error fetching deleted users: {e}")
        return []

def restore_deleted_user(deleted_id: int):
    """Restore a deleted user from backup"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM deleted_users WHERE id = ?", (deleted_id,))
        backup_row = cursor.fetchone()
        
        if not backup_row:
            conn.close()
            return False, 'Deleted user not found'
        
        backup = dict(backup_row)
        user_data = from_json(backup['data'])
        
        # Remove id and created_at to let SQLite generate new ones
        user_data.pop('id', None)
        user_data.pop('created_at', None)
        
        cursor.execute("""
            INSERT INTO students (
                public_id, phone_number, password, first_name,
                middle_name, last_name, location, city, school, grade,
                total_points, is_admin, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_data.get('public_id'),
            user_data['phone_number'],
            user_data['password'],
            user_data['first_name'],
            user_data.get('middle_name', ''),
            user_data['last_name'],
            user_data.get('location', ''),
            user_data.get('city', ''),
            user_data.get('school', ''),
            user_data.get('grade', ''),
            user_data.get('total_points', 0),
            user_data.get('is_admin', 0),
            user_data.get('created_at', now())
        ))
        
        cursor.execute("DELETE FROM deleted_users WHERE id = ?", (deleted_id,))
        
        conn.commit()
        conn.close()
        return True, 'User restored successfully'
        
    except Exception as e:
        print(f"Error restoring user: {e}")
        return False, str(e)

# ============================================
# GROUP FUNCTIONS
# ============================================

def get_all_groups():
    """Get all groups (admin only)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM groups ORDER BY created_at DESC")
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error fetching groups: {e}")
        return []

def get_active_groups():
    """Get all active groups"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM groups WHERE is_active = 1 ORDER BY created_at DESC")
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error fetching groups: {e}")
        return []

def create_group(data: dict):
    """Create a new group"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO groups (
                name, platform, invite_link, description, category,
                click_count, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['name'],
            data['platform'],
            data['invite_link'],
            data.get('description', ''),
            data.get('category', ''),
            data.get('click_count', 0),
            data.get('is_active', 1),
            now()
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error creating group: {e}")
        return False

def delete_group(group_id: int):
    """Delete a group"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting group: {e}")
        return False

def track_group_click(group_id: int):
    """Increment click count for a group"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE groups SET click_count = click_count + 1 WHERE id = ?",
            (group_id,)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error tracking group click: {e}")
        return False

def get_group_by_id(group_id: int):
    """Get a group by ID"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM groups WHERE id = ?", (group_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        print(f"Error fetching group: {e}")
        return None

# ============================================
# PDF FUNCTIONS
# ============================================

def get_all_pdfs():
    """Get all PDFs"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pdfs ORDER BY created_at DESC")
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error fetching PDFs: {e}")
        return []

def get_pdf_by_id(pdf_id: int):
    """Get a PDF by ID"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pdfs WHERE id = ?", (pdf_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        print(f"Error fetching PDF: {e}")
        return None

def create_pdf(data: dict):
    """Create a new PDF"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pdfs (
                title, description, file_url, telegram_download_url,
                subject, grade, category, view_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['title'],
            data.get('description', ''),
            data['file_url'],
            data['telegram_download_url'],
            data.get('subject', ''),
            data.get('grade', ''),
            data.get('category', ''),
            data.get('view_count', 0),
            now()
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error creating PDF: {e}")
        return False

def delete_pdf(pdf_id: int):
    """Delete a PDF"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pdfs WHERE id = ?", (pdf_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting PDF: {e}")
        return False

def increment_pdf_view(pdf_id: int):
    """Increment view count for a PDF"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE pdfs SET view_count = view_count + 1 WHERE id = ?",
            (pdf_id,)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error incrementing PDF view: {e}")
        return False

def get_pdf_distinct_subjects():
    """Get distinct subjects from PDFs"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT subject FROM pdfs WHERE subject IS NOT NULL AND subject != ''")
        results = cursor.fetchall()
        conn.close()
        return [row['subject'] for row in results]
    except Exception as e:
        print(f"Error fetching PDF subjects: {e}")
        return []

def get_pdf_distinct_grades():
    """Get distinct grades from PDFs"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT grade FROM pdfs WHERE grade IS NOT NULL AND grade != ''")
        results = cursor.fetchall()
        conn.close()
        return [row['grade'] for row in results]
    except Exception as e:
        print(f"Error fetching PDF grades: {e}")
        return []

def search_pdfs(search: str = '', subject: str = '', grade: str = ''):
    """Search PDFs with filters"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        query = "SELECT * FROM pdfs WHERE 1=1"
        params = []
        
        if search:
            query += " AND (title LIKE ? OR description LIKE ?)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])
        
        if subject:
            query += " AND subject = ?"
            params.append(subject)
        
        if grade:
            query += " AND grade = ?"
            params.append(grade)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error searching PDFs: {e}")
        return []

# ============================================
# LIVE QUIZ FUNCTIONS
# ============================================

def create_live_quiz(data: dict):
    """Create a new live quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO live_quizzes (
                creator_id, title, subject_id, question_count, join_code,
                status, max_participants, time_per_question, current_question_index,
                question_ids, started_at, ended_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['creator_id'],
            data.get('title', ''),
            data['subject_id'],
            data['question_count'],
            data['join_code'],
            data.get('status', 'waiting'),
            data.get('max_participants', 50),
            data.get('time_per_question', 30),
            data.get('current_question_index', 0),
            to_json(data.get('question_ids', [])),
            data.get('started_at'),
            data.get('ended_at'),
            now()
        ))
        conn.commit()
        
        cursor.execute("SELECT * FROM live_quizzes WHERE join_code = ?", (data['join_code'],))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        print(f"Error creating live quiz: {e}")
        return None

def get_live_quiz_by_id(quiz_id: int):
    """Get a live quiz by ID"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            return quiz
        return None
    except Exception as e:
        print(f"Error fetching live quiz: {e}")
        return None

def get_live_quiz_by_code(join_code: str):
    """Get a live quiz by join code"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM live_quizzes WHERE join_code = ?", (join_code,))
        result = cursor.fetchone()
        conn.close()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            return quiz
        return None
    except Exception as e:
        print(f"Error fetching live quiz: {e}")
        return None

def get_live_quiz_with_subject(quiz_id: int):
    """Get live quiz with subject name"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT lq.*, s.name as subject_name
            FROM live_quizzes lq
            LEFT JOIN subjects s ON lq.subject_id = s.id
            WHERE lq.id = ?
        """, (quiz_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            quiz['subjects'] = {'name': quiz.pop('subject_name', '')} if quiz.get('subject_name') else None
            return quiz
        return None
    except Exception as e:
        print(f"Error fetching live quiz: {e}")
        return None

def update_live_quiz(quiz_id: int, data: dict):
    """Update a live quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        fields = []
        params = []
        
        for key, value in data.items():
            if key == 'question_ids':
                fields.append(f"{key} = ?")
                params.append(to_json(value))
            elif key in ['started_at', 'ended_at']:
                fields.append(f"{key} = ?")
                params.append(value)
            else:
                fields.append(f"{key} = ?")
                params.append(value)
        
        params.append(quiz_id)
        query = f"UPDATE live_quizzes SET {', '.join(fields)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating live quiz: {e}")
        return False

def get_live_quiz_participants(quiz_id: int):
    """Get all participants for a live quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT lqp.*, s.first_name, s.last_name, s.public_id
            FROM live_quiz_participants lqp
            LEFT JOIN students s ON lqp.student_id = s.id
            WHERE lqp.quiz_id = ?
            ORDER BY lqp.joined_at
        """, (quiz_id,))
        results = cursor.fetchall()
        conn.close()
        
        participants = []
        for row in results:
            p = dict(row)
            p['answers'] = from_json(p['answers'])
            p['ratings'] = from_json(p['ratings'])
            p['student'] = {
                'first_name': p.pop('first_name', ''),
                'last_name': p.pop('last_name', ''),
                'public_id': p.pop('public_id', '')
            }
            participants.append(p)
        return participants
    except Exception as e:
        print(f"Error fetching participants: {e}")
        return []

def get_live_quiz_participant(quiz_id: int, student_id: int):
    """Get a specific participant"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM live_quiz_participants
            WHERE quiz_id = ? AND student_id = ?
        """, (quiz_id, student_id))
        result = cursor.fetchone()
        conn.close()
        if result:
            p = dict(result)
            p['answers'] = from_json(p['answers'])
            p['ratings'] = from_json(p['ratings'])
            return p
        return None
    except Exception as e:
        print(f"Error fetching participant: {e}")
        return None

def add_live_quiz_participant(quiz_id: int, student_id: int):
    """Add a participant to a live quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO live_quiz_participants (
                quiz_id, student_id, score, current_question_index,
                correct_count, wrong_count, skipped_count, answers, ratings,
                ranking, status, joined_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            quiz_id,
            student_id,
            0,
            0,
            0,
            0,
            0,
            to_json({}),
            to_json({}),
            None,
            'active',
            now()
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error adding participant: {e}")
        return False

def update_live_quiz_participant(participant_id: int, data: dict):
    """Update a participant"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        fields = []
        params = []
        
        for key, value in data.items():
            if key in ['answers', 'ratings']:
                fields.append(f"{key} = ?")
                params.append(to_json(value))
            else:
                fields.append(f"{key} = ?")
                params.append(value)
        
        params.append(participant_id)
        query = f"UPDATE live_quiz_participants SET {', '.join(fields)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating participant: {e}")
        return False

def get_live_quiz_participants_with_names(quiz_id: int):
    """Get participants with student names for leaderboard"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT lqp.*, s.first_name, s.last_name, s.public_id
            FROM live_quiz_participants lqp
            LEFT JOIN students s ON lqp.student_id = s.id
            WHERE lqp.quiz_id = ?
            ORDER BY lqp.score DESC
        """, (quiz_id,))
        results = cursor.fetchall()
        conn.close()
        
        participants = []
        for row in results:
            p = dict(row)
            p['answers'] = from_json(p['answers'])
            p['ratings'] = from_json(p['ratings'])
            p['student'] = {
                'first_name': p.pop('first_name', ''),
                'last_name': p.pop('last_name', ''),
                'public_id': p.pop('public_id', '')
            }
            participants.append(p)
        return participants
    except Exception as e:
        print(f"Error fetching participants: {e}")
        return []

def get_active_live_quiz(join_code: str):
    """Get an active live quiz by join code"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM live_quizzes
            WHERE join_code = ? AND status = 'waiting'
        """, (join_code,))
        result = cursor.fetchone()
        conn.close()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            return quiz
        return None
    except Exception as e:
        print(f"Error fetching active quiz: {e}")
        return None

def get_live_quiz_count(quiz_id: int):
    """Get number of participants in a live quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM live_quiz_participants WHERE quiz_id = ?",
            (quiz_id,)
        )
        result = cursor.fetchone()
        conn.close()
        return result['count'] if result else 0
    except Exception as e:
        print(f"Error getting participant count: {e}")
        return 0

def get_live_quiz_completed_count(quiz_id: int):
    """Get number of participants who completed the quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM live_quiz_participants 
            WHERE quiz_id = ? AND current_question_index >= (
                SELECT question_count FROM live_quizzes WHERE id = ?
            )
        """, (quiz_id, quiz_id))
        result = cursor.fetchone()
        conn.close()
        return result['count'] if result else 0
    except Exception as e:
        print(f"Error getting completed count: {e}")
        return 0

def get_question_ids_for_quiz(quiz_id: int):
    """Get question IDs for a live quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT question_ids FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return from_json(result['question_ids'])
        return []
    except Exception as e:
        print(f"Error getting question IDs: {e}")
        return []

def get_questions_by_ids(question_ids: list):
    """Get questions by IDs"""
    if not question_ids:
        return []
    try:
        conn = get_db()
        cursor = conn.cursor()
        placeholders = ','.join(['?' for _ in question_ids])
        cursor.execute(f"""
            SELECT id, question_text, options, correct_answer, explanation
            FROM questions
            WHERE id IN ({placeholders})
        """, question_ids)
        results = cursor.fetchall()
        conn.close()
        
        questions = []
        for row in results:
            q = dict(row)
            q['options'] = from_json(q['options'])
            questions.append(q)
        return questions
    except Exception as e:
        print(f"Error fetching questions by IDs: {e}")
        return []

def update_participant_rankings(quiz_id: int):
    """Update ranking for all participants in a quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id FROM live_quiz_participants
            WHERE quiz_id = ?
            ORDER BY score DESC
        """, (quiz_id,))
        results = cursor.fetchall()
        
        for i, row in enumerate(results, 1):
            cursor.execute(
                "UPDATE live_quiz_participants SET ranking = ? WHERE id = ?",
                (i, row['id'])
            )
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating rankings: {e}")
        return False

def get_live_quiz_creator_id(quiz_id: int):
    """Get the creator ID of a live quiz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT creator_id FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        conn.close()
        return result['creator_id'] if result else None
    except Exception as e:
        print(f"Error getting creator ID: {e}")
        return None

def get_group_categories():
    """Get all unique group categories"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT category FROM groups 
            WHERE category IS NOT NULL AND category != '' AND is_active = 1
        """)
        results = cursor.fetchall()
        conn.close()
        return [row['category'] for row in results]
    except Exception as e:
        print(f"Error fetching group categories: {e}")
        return []

def search_groups(search: str = '', platform: str = '', category: str = ''):
    """Search groups with filters"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        query = "SELECT * FROM groups WHERE is_active = 1"
        params = []
        
        if search:
            query += " AND (name LIKE ? OR description LIKE ?)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])
        
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error searching groups: {e}")
        return []