import sqlite3
import json
import secrets
import string
from datetime import datetime, timezone, timedelta
from config import Config
from utils import get_somali_time, get_somali_time_db, format_somali_time
from flask import g, current_app
import time
import os

# ============================================
# DATABASE CONFIGURATION
# ============================================

DB_PATH = Config.DATABASE_PATH
MAX_RETRIES = 3
RETRY_DELAY = 0.1  # Initial delay, increases with backoff
WAL_CHECKPOINT_INTERVAL = 100  # Checkpoint every 100 write operations

# Track write operations for checkpointing
_write_counter = 0


# ============================================
# CONNECTION MANAGEMENT (Request-Scoped)
# ============================================

def get_db():
    """
    Get a database connection for the current request context.
    Uses Flask's `g` object for request-scoped connections.
    Automatically closes when the request ends.
    """
    if 'db' not in g:
        try:
            # Ensure directory exists
            db_dir = os.path.dirname(DB_PATH)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
            
            # Create connection with timeout
            conn = sqlite3.connect(
                DB_PATH,
                timeout=Config.DB_TIMEOUT if hasattr(Config, 'DB_TIMEOUT') else 10.0
            )
            
            # Enable features
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(f"PRAGMA busy_timeout = {Config.DB_BUSY_TIMEOUT if hasattr(Config, 'DB_BUSY_TIMEOUT') else 10000}")
            
            # Optimize WAL mode
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
            
            # Store in g
            g.db = conn
            
        except sqlite3.Error as e:
            current_app.logger.error(f"Database connection error: {e}")
            raise
    
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    """
    Close the database connection when the request context ends.
    This ensures connections don't leak between requests.
    """
    db = g.pop('db', None)
    if db is not None:
        try:
            # Force checkpoint if there were many writes
            global _write_counter
            if _write_counter >= WAL_CHECKPOINT_INTERVAL:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                _write_counter = 0
            db.close()
        except Exception as e:
            current_app.logger.warning(f"Error closing database: {e}")


# ============================================
# TRANSACTION HELPERS
# ============================================

class transaction:
    """Context manager for database transactions with automatic commit/rollback."""
    
    def __init__(self, autocommit=True):
        self.autocommit = autocommit
        self.conn = None
        self.cursor = None
    
    def __enter__(self):
        self.conn = get_db()
        self.cursor = self.conn.cursor()
        return self.cursor
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.autocommit:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        self.cursor = None


def execute_with_retry(query, params=(), max_retries=MAX_RETRIES, commit=True):
    """
    Execute a query with automatic retry on database lock errors.
    Uses exponential backoff to reduce contention.
    
    Args:
        query: SQL query string
        params: Parameters for the query
        max_retries: Maximum number of retry attempts
        commit: Whether to commit after execution
    
    Returns:
        sqlite3.Cursor object
    """
    for attempt in range(max_retries):
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(query, params)
            if commit:
                conn.commit()
            
            # Track writes for checkpointing
            global _write_counter
            if query.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER')):
                _write_counter += 1
            
            return cursor
            
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            
            # Retry on lock or busy errors
            if ('database is locked' in error_msg or 
                'database is busy' in error_msg or 
                'unable to open database' in error_msg):
                
                if attempt < max_retries - 1:
                    wait_time = RETRY_DELAY * (2 ** attempt)  # 0.1, 0.2, 0.4, ...
                    time.sleep(wait_time)
                    continue
            
            # For other errors, rollback if needed
            try:
                conn = get_db()
                conn.rollback()
            except:
                pass
            raise
        
        except sqlite3.IntegrityError as e:
            # Rollback on integrity errors
            try:
                conn = get_db()
                conn.rollback()
            except:
                pass
            raise
        
        except Exception as e:
            # Rollback on any other error
            try:
                conn = get_db()
                conn.rollback()
            except:
                pass
            raise
    
    # If we get here, all retries failed
    raise sqlite3.OperationalError("Database operation failed after maximum retries")


def execute_many_with_retry(query, params_list, max_retries=MAX_RETRIES):
    """
    Execute a query with multiple parameter sets in a single transaction.
    Uses automatic retry on database lock errors.
    """
    for attempt in range(max_retries):
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            
            # Track writes
            global _write_counter
            if query.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                _write_counter += len(params_list)
            
            return cursor
            
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if ('database is locked' in error_msg or 
                'database is busy' in error_msg):
                if attempt < max_retries - 1:
                    wait_time = RETRY_DELAY * (2 ** attempt)
                    time.sleep(wait_time)
                    continue
            try:
                conn = get_db()
                conn.rollback()
            except:
                pass
            raise
        
        except Exception as e:
            try:
                conn = get_db()
                conn.rollback()
            except:
                pass
            raise


# ============================================
# JSON HELPERS
# ============================================

def to_json(data):
    """Convert data to JSON string, handling None values."""
    return json.dumps(data) if data is not None else None

def from_json(data):
    """Parse JSON string to Python object, handling None values."""
    return json.loads(data) if data else None


# ============================================
# TIME HELPERS
# ============================================

def now():
    """Get current time in Somali timezone as string."""
    return get_somali_time_db()


# ============================================
# PUBLIC ID GENERATION
# ============================================

PUBLIC_ID_CHARS = string.ascii_uppercase + '123456789'

def generate_public_id() -> str:
    """Generate a unique 4-character alphanumeric public ID."""
    return ''.join(secrets.choice(PUBLIC_ID_CHARS) for _ in range(4))

def get_student_by_public_id(public_id: str):
    """Get student by public ID."""
    cursor = execute_with_retry("SELECT * FROM students WHERE public_id = ?", (public_id,))
    result = cursor.fetchone()
    return dict(result) if result else None


# ============================================
# STUDENT FUNCTIONS
# ============================================

def get_student_by_phone(phone: str):
    """Get student by phone number."""
    cursor = execute_with_retry("SELECT * FROM students WHERE phone_number = ?", (phone,))
    result = cursor.fetchone()
    return dict(result) if result else None

def get_student_by_id(student_id: int):
    """Get student by internal ID."""
    cursor = execute_with_retry("SELECT * FROM students WHERE id = ?", (student_id,))
    result = cursor.fetchone()
    return dict(result) if result else None

def create_student(data: dict):
    """Create a new student with auto-generated public_id."""
    try:
        public_id = generate_public_id()
        while get_student_by_public_id(public_id):
            public_id = generate_public_id()
        
        cursor = execute_with_retry("""
            INSERT INTO students (
                public_id, phone_number, password, first_name,
                middle_name, last_name, location, city, school, grade,
                total_points, is_admin, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            public_id,
            data['phone_number'],
            data['password'],
            data['first_name'],
            data.get('middle_name', ''),
            data['last_name'],
            data.get('location', ''),
            data.get('city', ''),
            data.get('school', ''),
            data.get('grade', ''),
            data.get('total_points', 0),
            0,
            now()
        ), commit=True)
        
        return get_student_by_phone(data['phone_number'])
    except Exception as e:
        current_app.logger.error(f"Error creating student: {e}")
        return None

def update_student_points(student_id: int, points: int):
    """Update student's total points."""
    try:
        execute_with_retry(
            "UPDATE students SET total_points = ? WHERE id = ?",
            (points, student_id),
            commit=True
        )
        return get_student_by_id(student_id)
    except Exception as e:
        current_app.logger.error(f"Error updating points: {e}")
        return None

def is_admin(user_id: int) -> bool:
    """Check if a user is an admin."""
    try:
        cursor = execute_with_retry("SELECT is_admin FROM students WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return bool(result['is_admin']) if result else False
    except Exception as e:
        current_app.logger.error(f"Error checking admin: {e}")
        return False

def toggle_admin(user_id: int):
    """Toggle admin status for a user."""
    try:
        cursor = execute_with_retry("SELECT is_admin FROM students WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        if not result:
            return None
        
        new_status = 0 if result['is_admin'] else 1
        execute_with_retry(
            "UPDATE students SET is_admin = ? WHERE id = ?",
            (new_status, user_id),
            commit=True
        )
        return get_student_by_id(user_id)
    except Exception as e:
        current_app.logger.error(f"Error toggling admin: {e}")
        return None

def get_all_students():
    """Get all students (admin only)."""
    try:
        cursor = execute_with_retry("""
            SELECT id, public_id, first_name, last_name, phone_number, 
                   location, school, grade, total_points, is_admin, created_at
            FROM students
            ORDER BY created_at DESC
        """)
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching students: {e}")
        return []

def get_schools_by_location(location: str):
    """Get schools by location."""
    try:
        cursor = execute_with_retry("SELECT * FROM schools WHERE location = ?", (location,))
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching schools: {e}")
        return []


# ============================================
# SUBJECT FUNCTIONS
# ============================================

def get_all_subjects():
    """Get all subjects."""
    try:
        cursor = execute_with_retry("SELECT * FROM subjects ORDER BY name")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching subjects: {e}")
        return []

def get_subject_by_id(subject_id: int):
    """Get subject by ID."""
    try:
        cursor = execute_with_retry("SELECT * FROM subjects WHERE id = ?", (subject_id,))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        current_app.logger.error(f"Error fetching subject: {e}")
        return None

def get_subject_by_name(name: str):
    """Get subject by name (case-insensitive)."""
    try:
        cursor = execute_with_retry("SELECT * FROM subjects WHERE LOWER(name) = LOWER(?)", (name,))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        current_app.logger.error(f"Error fetching subject: {e}")
        return None

def create_subject(data: dict):
    """Create a new subject."""
    try:
        execute_with_retry("""
            INSERT INTO subjects (name, icon)
            VALUES (?, ?)
        """, (data['name'], data.get('icon', '📚')), commit=True)
        return get_subject_by_name(data['name'])
    except Exception as e:
        current_app.logger.error(f"Error creating subject: {e}")
        return None

def delete_subject(subject_id: int):
    """Delete a subject."""
    try:
        execute_with_retry("DELETE FROM subjects WHERE id = ?", (subject_id,), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error deleting subject: {e}")
        return False


# ============================================
# QUESTION FUNCTIONS
# ============================================

def get_questions_by_subject(subject_id: int, limit: int = 10):
    """Get random questions for a subject."""
    try:
        cursor = execute_with_retry("""
            SELECT id, question_text, options, correct_answer, explanation
            FROM questions
            WHERE subject_id = ? AND status = 'active'
            ORDER BY RANDOM()
            LIMIT ?
        """, (subject_id, limit))
        results = cursor.fetchall()
        
        questions = []
        for row in results:
            q = dict(row)
            q['options'] = from_json(q['options'])
            questions.append(q)
        return questions
    except Exception as e:
        current_app.logger.error(f"Error fetching questions: {e}")
        return []

def get_all_questions():
    """Get all questions with subject names (admin only)."""
    try:
        cursor = execute_with_retry("""
            SELECT q.*, s.name as subject_name
            FROM questions q
            LEFT JOIN subjects s ON q.subject_id = s.id
            ORDER BY q.created_at DESC
        """)
        results = cursor.fetchall()
        
        questions = []
        for row in results:
            q = dict(row)
            q['options'] = from_json(q['options'])
            q['subjects'] = {'name': q.pop('subject_name', '')} if q.get('subject_name') else None
            questions.append(q)
        return questions
    except Exception as e:
        current_app.logger.error(f"Error fetching questions: {e}")
        return []

def create_question(data: dict):
    """Create a new question."""
    try:
        execute_with_retry("""
            INSERT INTO questions (
                subject_id, question_text, options, correct_answer,
                difficulty, chapter, tags, explanation,
                created_by, updated_by, status, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['subject_id'],
            data['question_text'],
            to_json(data['options']),
            data['correct_answer'],
            data.get('difficulty', 1),
            data.get('chapter', ''),
            data.get('tags', ''),
            data.get('explanation', ''),
            data.get('created_by'),
            data.get('updated_by'),
            data.get('status', 'active'),
            data.get('version', 1),
            now(),
            now()
        ), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error creating question: {e}")
        return False

def bulk_create_questions(questions_data: list, admin_id: int):
    """Bulk create multiple questions in a single transaction."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        imported_count = 0
        errors = []
        
        # Use a single transaction for all inserts
        for idx, q in enumerate(questions_data, 1):
            try:
                cursor.execute("""
                    INSERT INTO questions (
                        subject_id, question_text, options, correct_answer,
                        difficulty, chapter, tags, explanation,
                        created_by, updated_by, status, version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    q['subject_id'],
                    q['question_text'],
                    to_json(q['options']),
                    q['correct_answer'],
                    q.get('difficulty', 1),
                    q.get('chapter', ''),
                    q.get('tags', ''),
                    q.get('explanation', ''),
                    admin_id,
                    admin_id,
                    'active',
                    1,
                    now(),
                    now()
                ))
                imported_count += 1
            except Exception as e:
                errors.append({
                    'index': idx,
                    'question': q.get('question_text', 'Unknown'),
                    'error': str(e)
                })
                # Continue with next question
        
        conn.commit()
        
        # Track writes
        global _write_counter
        _write_counter += imported_count
        
        return {
            'imported': imported_count,
            'errors': errors,
            'total': len(questions_data)
        }
        
    except Exception as e:
        current_app.logger.error(f"Error in bulk create: {e}")
        try:
            get_db().rollback()
        except:
            pass
        return {
            'imported': 0,
            'errors': [{'error': str(e)}],
            'total': len(questions_data)
        }

def update_question(question_id: int, data: dict):
    """Update a question."""
    try:
        execute_with_retry("""
            UPDATE questions SET
                subject_id = ?,
                question_text = ?,
                options = ?,
                correct_answer = ?,
                difficulty = ?,
                chapter = ?,
                tags = ?,
                explanation = ?,
                updated_by = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            data['subject_id'],
            data['question_text'],
            to_json(data['options']),
            data['correct_answer'],
            data.get('difficulty', 1),
            data.get('chapter', ''),
            data.get('tags', ''),
            data.get('explanation', ''),
            data.get('updated_by'),
            now(),
            question_id
        ), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error updating question: {e}")
        return False

def delete_question(question_id: int):
    """Soft delete a question (set status to archived)."""
    try:
        execute_with_retry(
            "UPDATE questions SET status = 'archived' WHERE id = ?",
            (question_id,),
            commit=True
        )
        return True
    except Exception as e:
        current_app.logger.error(f"Error deleting question: {e}")
        return False

def get_question_by_id(question_id: int):
    """Get a question by ID."""
    try:
        cursor = execute_with_retry("SELECT * FROM questions WHERE id = ?", (question_id,))
        result = cursor.fetchone()
        if result:
            q = dict(result)
            q['options'] = from_json(q['options'])
            return q
        return None
    except Exception as e:
        current_app.logger.error(f"Error fetching question: {e}")
        return None

def check_question_exists(question_text: str, subject_id: int):
    """Check if a question already exists."""
    try:
        cursor = execute_with_retry(
            "SELECT id FROM questions WHERE LOWER(question_text) = LOWER(?) AND subject_id = ? AND status = 'active'",
            (question_text, subject_id)
        )
        result = cursor.fetchone()
        return result is not None
    except Exception as e:
        current_app.logger.error(f"Error checking question: {e}")
        return False


# ============================================
# QUIZ ATTEMPT FUNCTIONS
# ============================================

def save_quiz_attempt(student_id: int, subject_id: int, score: int, total: int, answers: list, ratings: list):
    """Save a quiz attempt."""
    try:
        execute_with_retry("""
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
        ), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error saving quiz attempt: {e}")
        return None

def get_user_quiz_history(student_id: int, limit: int = 10):
    """Get user's quiz history."""
    try:
        cursor = execute_with_retry("""
            SELECT qa.*, s.name as subject_name
            FROM quiz_attempts qa
            LEFT JOIN subjects s ON qa.subject_id = s.id
            WHERE qa.student_id = ?
            ORDER BY qa.completed_at DESC
            LIMIT ?
        """, (student_id, limit))
        results = cursor.fetchall()
        
        attempts = []
        for row in results:
            a = dict(row)
            a['subjects'] = {'name': a.pop('subject_name', '')} if a.get('subject_name') else None
            a['answers'] = from_json(a['answers'])
            a['ratings'] = from_json(a['ratings'])
            attempts.append(a)
        return attempts
    except Exception as e:
        current_app.logger.error(f"Error fetching quiz history: {e}")
        return []

def get_leaderboard(limit: int = 20):
    """Get global leaderboard."""
    try:
        cursor = execute_with_retry("""
            SELECT public_id, first_name, last_name, total_points, school
            FROM students
            ORDER BY total_points DESC
            LIMIT ?
        """, (limit,))
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching leaderboard: {e}")
        return []


# ============================================
# DELETED USERS FUNCTIONS
# ============================================

def delete_user(student_id: int, admin_id: int, keep_ratings: bool = True, delete_attempts: bool = True):
    """Delete a user and backup their data."""
    try:
        user = get_student_by_id(student_id)
        if not user:
            return None, 'User not found'
        
        if student_id == admin_id:
            return None, 'You cannot delete your own account'
        
        # Insert into deleted_users
        execute_with_retry("""
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
        ), commit=True)
        
        if delete_attempts:
            execute_with_retry("DELETE FROM quiz_attempts WHERE student_id = ?", (student_id,), commit=True)
        
        if not keep_ratings:
            execute_with_retry("DELETE FROM quiz_ratings WHERE student_id = ?", (student_id,), commit=True)
        
        execute_with_retry("DELETE FROM students WHERE id = ?", (student_id,), commit=True)
        
        return True, 'User deleted successfully'
        
    except Exception as e:
        current_app.logger.error(f"Error deleting user: {e}")
        return False, str(e)

def get_deleted_users(limit: int = 50):
    """Get list of deleted users for admin recovery."""
    try:
        cursor = execute_with_retry("""
            SELECT d.*, s.first_name as admin_first_name, s.last_name as admin_last_name, s.public_id as admin_public_id
            FROM deleted_users d
            LEFT JOIN students s ON d.deleted_by = s.id
            ORDER BY d.deleted_at DESC
            LIMIT ?
        """, (limit,))
        results = cursor.fetchall()
        
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
        current_app.logger.error(f"Error fetching deleted users: {e}")
        return []

def restore_deleted_user(deleted_id: int):
    """Restore a deleted user from backup."""
    try:
        cursor = execute_with_retry("SELECT * FROM deleted_users WHERE id = ?", (deleted_id,))
        backup_row = cursor.fetchone()
        
        if not backup_row:
            return False, 'Deleted user not found'
        
        backup = dict(backup_row)
        user_data = from_json(backup['data'])
        
        user_data.pop('id', None)
        user_data.pop('created_at', None)
        
        execute_with_retry("""
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
        ), commit=True)
        
        execute_with_retry("DELETE FROM deleted_users WHERE id = ?", (deleted_id,), commit=True)
        
        return True, 'User restored successfully'
        
    except Exception as e:
        current_app.logger.error(f"Error restoring user: {e}")
        return False, str(e)


# ============================================
# GROUP FUNCTIONS
# ============================================

def get_all_groups():
    """Get all groups (admin only)."""
    try:
        cursor = execute_with_retry("SELECT * FROM groups ORDER BY created_at DESC")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching groups: {e}")
        return []

def get_active_groups():
    """Get all active groups."""
    try:
        cursor = execute_with_retry("SELECT * FROM groups WHERE is_active = 1 ORDER BY created_at DESC")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching groups: {e}")
        return []

def create_group(data: dict):
    """Create a new group."""
    try:
        execute_with_retry("""
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
        ), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error creating group: {e}")
        return False

def delete_group(group_id: int):
    """Delete a group."""
    try:
        execute_with_retry("DELETE FROM groups WHERE id = ?", (group_id,), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error deleting group: {e}")
        return False

def track_group_click(group_id: int):
    """Increment click count for a group."""
    try:
        execute_with_retry(
            "UPDATE groups SET click_count = click_count + 1 WHERE id = ?",
            (group_id,),
            commit=True
        )
        return True
    except Exception as e:
        current_app.logger.error(f"Error tracking group click: {e}")
        return False

def get_group_by_id(group_id: int):
    """Get a group by ID."""
    try:
        cursor = execute_with_retry("SELECT * FROM groups WHERE id = ?", (group_id,))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        current_app.logger.error(f"Error fetching group: {e}")
        return None


# ============================================
# PDF FUNCTIONS
# ============================================

def get_all_pdfs():
    """Get all PDFs."""
    try:
        cursor = execute_with_retry("SELECT * FROM pdfs ORDER BY created_at DESC")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching PDFs: {e}")
        return []

def get_pdf_by_id(pdf_id: int):
    """Get a PDF by ID."""
    try:
        cursor = execute_with_retry("SELECT * FROM pdfs WHERE id = ?", (pdf_id,))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        current_app.logger.error(f"Error fetching PDF: {e}")
        return None

def create_pdf(data: dict):
    """Create a new PDF."""
    try:
        execute_with_retry("""
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
        ), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error creating PDF: {e}")
        return False

def delete_pdf(pdf_id: int):
    """Delete a PDF."""
    try:
        execute_with_retry("DELETE FROM pdfs WHERE id = ?", (pdf_id,), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error deleting PDF: {e}")
        return False

def increment_pdf_view(pdf_id: int):
    """Increment view count for a PDF."""
    try:
        execute_with_retry(
            "UPDATE pdfs SET view_count = view_count + 1 WHERE id = ?",
            (pdf_id,),
            commit=True
        )
        return True
    except Exception as e:
        current_app.logger.error(f"Error incrementing PDF view: {e}")
        return False

def get_pdf_distinct_subjects():
    """Get distinct subjects from PDFs."""
    try:
        cursor = execute_with_retry("SELECT DISTINCT subject FROM pdfs WHERE subject IS NOT NULL AND subject != ''")
        results = cursor.fetchall()
        return [row['subject'] for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching PDF subjects: {e}")
        return []

def get_pdf_distinct_grades():
    """Get distinct grades from PDFs."""
    try:
        cursor = execute_with_retry("SELECT DISTINCT grade FROM pdfs WHERE grade IS NOT NULL AND grade != ''")
        results = cursor.fetchall()
        return [row['grade'] for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching PDF grades: {e}")
        return []

def search_pdfs(search: str = '', subject: str = '', grade: str = ''):
    """Search PDFs with filters."""
    try:
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
        
        cursor = execute_with_retry(query, params)
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error searching PDFs: {e}")
        return []


# ============================================
# LIVE QUIZ FUNCTIONS
# ============================================

def create_live_quiz(data: dict):
    """Create a new live quiz."""
    try:
        execute_with_retry("""
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
        ), commit=True)
        
        cursor = execute_with_retry("SELECT * FROM live_quizzes WHERE join_code = ?", (data['join_code'],))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        current_app.logger.error(f"Error creating live quiz: {e}")
        return None

def get_live_quiz_by_id(quiz_id: int):
    """Get a live quiz by ID."""
    try:
        cursor = execute_with_retry("SELECT * FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            return quiz
        return None    except Exception as e:
        current_app.logger.error(f"Error fetching live quiz: {e}")
        return None

def get_live_quiz_by_code(join_code: str):
    """Get a live quiz by join code."""
    try:
        cursor = execute_with_retry("SELECT * FROM live_quizzes WHERE join_code = ?", (join_code,))
        result = cursor.fetchone()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            return quiz
        return None
    except Exception as e:
        current_app.logger.error(f"Error fetching live quiz: {e}")
        return None

def get_live_quiz_with_subject(quiz_id: int):
    """Get live quiz with subject name."""
    try:
        cursor = execute_with_retry("""
            SELECT lq.*, s.name as subject_name
            FROM live_quizzes lq
            LEFT JOIN subjects s ON lq.subject_id = s.id
            WHERE lq.id = ?
        """, (quiz_id,))
        result = cursor.fetchone()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            quiz['subjects'] = {'name': quiz.pop('subject_name', '')} if quiz.get('subject_name') else None
            return quiz
        return None
    except Exception as e:
        current_app.logger.error(f"Error fetching live quiz: {e}")
        return None

def update_live_quiz(quiz_id: int, data: dict):
    """Update a live quiz."""
    try:
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
        execute_with_retry(query, params, commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error updating live quiz: {e}")
        return False

def get_live_quiz_participants(quiz_id: int):
    """Get all participants for a live quiz."""
    try:
        cursor = execute_with_retry("""
            SELECT lqp.*, s.first_name, s.last_name, s.public_id
            FROM live_quiz_participants lqp
            LEFT JOIN students s ON lqp.student_id = s.id
            WHERE lqp.quiz_id = ?
            ORDER BY lqp.joined_at
        """, (quiz_id,))
        results = cursor.fetchall()
        
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
        current_app.logger.error(f"Error fetching participants: {e}")
        return []

def get_live_quiz_participant(quiz_id: int, student_id: int):
    """Get a specific participant."""
    try:
        cursor = execute_with_retry("""
            SELECT * FROM live_quiz_participants
            WHERE quiz_id = ? AND student_id = ?
        """, (quiz_id, student_id))
        result = cursor.fetchone()
        if result:
            p = dict(result)
            p['answers'] = from_json(p['answers'])
            p['ratings'] = from_json(p['ratings'])
            return p
        return None
    except Exception as e:
        current_app.logger.error(f"Error fetching participant: {e}")
        return None

def add_live_quiz_participant(quiz_id: int, student_id: int):
    """Add a participant to a live quiz."""
    try:
        execute_with_retry("""
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
        ), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error adding participant: {e}")
        return False

def update_live_quiz_participant(participant_id: int, data: dict):
    """Update a participant."""
    try:
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
        execute_with_retry(query, params, commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error updating participant: {e}")
        return False

def get_live_quiz_participants_with_names(quiz_id: int):
    """Get participants with student names for leaderboard."""
    try:
        cursor = execute_with_retry("""
            SELECT lqp.*, s.first_name, s.last_name, s.public_id
            FROM live_quiz_participants lqp
            LEFT JOIN students s ON lqp.student_id = s.id
            WHERE lqp.quiz_id = ?
            ORDER BY lqp.score DESC
        """, (quiz_id,))
        results = cursor.fetchall()
        
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
        current_app.logger.error(f"Error fetching participants: {e}")
        return []

def get_active_live_quiz(join_code: str):
    """Get an active live quiz by join code."""
    try:
        cursor = execute_with_retry("""
            SELECT * FROM live_quizzes
            WHERE join_code = ? AND status = 'waiting'
        """, (join_code,))
        result = cursor.fetchone()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            return quiz
        return None
    except Exception as e:
        current_app.logger.error(f"Error fetching active quiz: {e}")
        return None

def get_live_quiz_count(quiz_id: int):
    """Get number of participants in a live quiz."""
    try:
        cursor = execute_with_retry(
            "SELECT COUNT(*) as count FROM live_quiz_participants WHERE quiz_id = ?",
            (quiz_id,)
        )
        result = cursor.fetchone()
        return result['count'] if result else 0
    except Exception as e:
        current_app.logger.error(f"Error getting participant count: {e}")
        return 0

def get_live_quiz_completed_count(quiz_id: int):
    """Get number of participants who completed the quiz."""
    try:
        cursor = execute_with_retry("""
            SELECT COUNT(*) as count 
            FROM live_quiz_participants 
            WHERE quiz_id = ? AND current_question_index >= (
                SELECT question_count FROM live_quizzes WHERE id = ?
            )
        """, (quiz_id, quiz_id))
        result = cursor.fetchone()
        return result['count'] if result else 0
    except Exception as e:
        current_app.logger.error(f"Error getting completed count: {e}")
        return 0

def get_question_ids_for_quiz(quiz_id: int):
    """Get question IDs for a live quiz."""
    try:
        cursor = execute_with_retry("SELECT question_ids FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        if result:
            return from_json(result['question_ids'])
        return []
    except Exception as e:
        current_app.logger.error(f"Error getting question IDs: {e}")
        return []

def get_questions_by_ids(question_ids: list):
    """Get questions by IDs."""
    if not question_ids:
        return []
    try:
        placeholders = ','.join(['?' for _ in question_ids])
        cursor = execute_with_retry(f"""
            SELECT id, question_text, options, correct_answer, explanation
            FROM questions
            WHERE id IN ({placeholders})
        """, question_ids)
        results = cursor.fetchall()
        
        questions = []
        for row in results:
            q = dict(row)
            q['options'] = from_json(q['options'])
            questions.append(q)
        return questions
    except Exception as e:
        current_app.logger.error(f"Error fetching questions by IDs: {e}")
        return []

def update_participant_rankings(quiz_id: int):
    """Update ranking for all participants in a quiz."""
    try:
        cursor = execute_with_retry("""
            SELECT id FROM live_quiz_participants
            WHERE quiz_id = ?
            ORDER BY score DESC
        """, (quiz_id,))
        results = cursor.fetchall()
        
        for i, row in enumerate(results, 1):
            execute_with_retry(
                "UPDATE live_quiz_participants SET ranking = ? WHERE id = ?",
                (i, row['id']),
                commit=True
            )
        
        return True
    except Exception as e:
        current_app.logger.error(f"Error updating rankings: {e}")
        return False

def get_live_quiz_creator_id(quiz_id: int):
    """Get the creator ID of a live quiz."""
    try:
        cursor = execute_with_retry("SELECT creator_id FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        return result['creator_id'] if result else None
    except Exception as e:
        current_app.logger.error(f"Error getting creator ID: {e}")
        return None

def get_group_categories():
    """Get all unique group categories."""
    try:
        cursor = execute_with_retry("""
            SELECT DISTINCT category FROM groups 
            WHERE category IS NOT NULL AND category != '' AND is_active = 1
        """)
        results = cursor.fetchall()
        return [row['category'] for row in results]
    except Exception as e:
        current_app.logger.error(f"Error fetching group categories: {e}")
        return []

def search_groups(search: str = '', platform: str = '', category: str = ''):
    """Search groups with filters."""
    try:
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
        
        cursor = execute_with_retry(query, params)
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error searching groups: {e}")
        return []


# ============================================
# NOTIFICATION FUNCTIONS
# ============================================

def create_notification(user_id, type, title, body, link='', icon=''):
    """Create a new notification for a user."""
    try:
        execute_with_retry("""
            INSERT INTO notifications (
                user_id, type, title, body, link, icon,
                is_read, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, type, title, body, link, icon,
            0, now()
        ), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error creating notification: {e}")
        return False

def create_notification_for_all_users(type, title, body, link='', icon=''):
    """Create notification for ALL users."""
    try:
        cursor = execute_with_retry("SELECT id FROM students")
        users = cursor.fetchall()
        
        for user in users:
            create_notification(user['id'], type, title, body, link, icon)
        
        return True
    except Exception as e:
        current_app.logger.error(f"Error creating notifications for all users: {e}")
        return False

def get_user_notifications(user_id, limit=20, unread_only=False):
    """Get notifications for a user."""
    try:
        query = """
            SELECT * FROM notifications 
            WHERE user_id = ?
        """
        params = [user_id]
        
        if unread_only:
            query += " AND is_read = 0"
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor = execute_with_retry(query, params)
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        current_app.logger.error(f"Error getting notifications: {e}")
        return []

def get_unread_count(user_id):
    """Get count of unread notifications."""
    try:
        cursor = execute_with_retry(
            "SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0",
            (user_id,)
        )
        result = cursor.fetchone()
        return result['count'] if result else 0
    except Exception as e:
        current_app.logger.error(f"Error getting unread count: {e}")
        return 0

def mark_notification_read(notification_id, user_id):
    """Mark a notification as read."""
    try:
        execute_with_retry("""
            UPDATE notifications 
            SET is_read = 1, read_at = ?
            WHERE id = ? AND user_id = ?
        """, (now(), notification_id, user_id), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error marking notification read: {e}")
        return False

def mark_all_notifications_read(user_id):
    """Mark all notifications as read."""
    try:
        execute_with_retry("""
            UPDATE notifications 
            SET is_read = 1, read_at = ?
            WHERE user_id = ? AND is_read = 0
        """, (now(), user_id), commit=True)
        return True
    except Exception as e:
        current_app.logger.error(f"Error marking all notifications read: {e}")
        return False


# ============================================
# NOTIFICATION TRIGGERS
# ============================================

def notify_quiz_completed(user_id, subject_name, score, total):
    """Send notification when quiz is completed."""
    percentage = round((score / total) * 100)
    title = "📝 Quiz Completed!"
    body = f"You scored {score}/{total} ({percentage}%) on {subject_name} Quiz!"
    create_notification(
        user_id=user_id,
        type='quiz_completed',
        title=title,
        body=body,
        link='/quiz/history',
        icon='📝'
    )

def notify_live_quiz_start(quiz_id, title, participants):
    """Send notification when live quiz starts."""
    for participant in participants:
        create_notification(
            user_id=participant['student_id'],
            type='live_quiz_start',
            title='⚡ Live Quiz Started!',
            body=f"🚀 '{title}' has started! Join now!",
            link=f'/live-quiz/play/{quiz_id}',
            icon='⚡'
        )

def notify_live_quiz_results(quiz_id, title, participants):
    """Send notification when live quiz ends."""
    for participant in participants:
        rank = participant.get('ranking', '?')
        score = participant.get('score', 0)
        create_notification(
            user_id=participant['student_id'],
            type='live_quiz_result',
            title='🏆 Live Quiz Results!',
            body=f"You ranked #{rank} in '{title}' with {score} points!",
            link=f'/live-quiz/results/{quiz_id}',
            icon='🏆'
        )

def notify_participant_joined(quiz_id, title, participant_name, creator_id):
    """Notify creator when someone joins."""
    create_notification(
        user_id=creator_id,
        type='participant_joined',
        title='👤 Participant Joined!',
        body=f"{participant_name} joined your quiz '{title}'",
        link=f'/live-quiz/waiting-room/{quiz_id}',
        icon='👤'
    )


# ============================================
# DATABASE INITIALIZATION
# ============================================

def init_db():
    """Initialize the database with schema from schema.sql."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        
        # Read schema
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        if os.path.exists(schema_path):
            with open(schema_path, 'r') as f:
                schema = f.read()
            conn.executescript(schema)
            conn.commit()
            current_app.logger.info("Database initialized successfully")
        else:
            current_app.logger.warning(f"Schema file not found: {schema_path}")
        
        conn.close()
        return True
    except Exception as e:
        current_app.logger.error(f"Error initializing database: {e}")
        return False


def close_db_connections():
    """
    Legacy function for compatibility.
    In the new system, connections are managed by Flask's teardown.
    """
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except:
            pass


# ============================================
# MIGRATION HELPERS
# ============================================

def ensure_wal_mode():
    """Ensure the database is in WAL mode."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.close()
        return True
    except Exception as e:
        current_app.logger.error(f"Error enabling WAL mode: {e}")
        return False


def checkpoint_wal():
    """Force a WAL checkpoint to reclaim space."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        return True
    except Exception as e:
        current_app.logger.error(f"Error checkpointing WAL: {e}")
        return False