import sqlite3
import json
import secrets
import string
import logging
import time
import os
from datetime import datetime, timezone, timedelta
from flask import g, current_app
from config import Config
from utils import get_somali_time, get_somali_time_db, format_somali_time

# ============================================
# DATABASE CONFIGURATION
# ============================================

DB_PATH = Config.DATABASE_PATH
MAX_RETRIES = Config.DB_RETRY_ATTEMPTS
INITIAL_DELAY = Config.DB_RETRY_INITIAL_DELAY
MAX_DELAY = Config.DB_MAX_RETRY_DELAY
BACKOFF_MULTIPLIER = Config.DB_RETRY_BACKOFF_MULTIPLIER
BULK_INSERT_BATCH_SIZE = 100

# Use standard logging for module-level operations
logger = logging.getLogger(__name__)


# ============================================
# RETRY UTILITY - Enhanced Exponential Backoff
# ============================================

def calculate_backoff(attempt: int) -> float:
    """
    Calculate exponential backoff delay.
    
    Attempt 0: 100ms
    Attempt 1: 200ms
    Attempt 2: 400ms
    Attempt 3: 800ms
    Attempt 4: 1.6s
    Attempt 5: 3.2s (capped at MAX_DELAY)
    
    Returns delay in seconds.
    """
    delay = INITIAL_DELAY * (BACKOFF_MULTIPLIER ** attempt)
    return min(delay, MAX_DELAY)


def is_retryable_error(error_msg: str) -> bool:
    """
    Determine if an error is retryable.
    Only retry on temporary database lock/busy errors.
    """
    error_msg = error_msg.lower()
    
    # Database lock errors - retryable
    if 'database is locked' in error_msg:
        return True
    if 'database is busy' in error_msg:
        return True
    if 'disk i/o error' in error_msg:
        return True  # Sometimes transient
    
    # Not retryable - these are permanent errors
    if 'no such table' in error_msg:
        return False
    if 'malformed' in error_msg:
        return False
    if 'corrupt' in error_msg:
        return False
    if 'integrity' in error_msg:
        return False
    if 'not null' in error_msg:
        return False
    if 'unique constraint' in error_msg:
        return False
    if 'foreign key' in error_msg:
        return False
    
    # Default: assume not retryable to avoid infinite loops
    return False


# ============================================
# CONNECTION MANAGEMENT (Request-Scoped)
# ============================================

def get_db():
    """Get a database connection for the current request context."""
    if 'db' not in g:
        try:
            # Ensure database directory exists
            db_dir = os.path.dirname(DB_PATH)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
            
            conn = sqlite3.connect(
                DB_PATH,
                timeout=Config.DB_TIMEOUT
            )
            
            conn.row_factory = sqlite3.Row
            
            # Enable WAL mode - CRITICAL for concurrent access
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(f"PRAGMA busy_timeout = {Config.DB_BUSY_TIMEOUT}")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = -64000")
            conn.execute("PRAGMA wal_autocheckpoint = 1000")
            
            # Verify WAL mode is actually enabled
            cursor = conn.execute("PRAGMA journal_mode")
            result = cursor.fetchone()
            if result and result[0].upper() != 'WAL':
                logger.warning(f"WAL mode not enabled! Got: {result[0]}")
                # Try to enable it again
                conn.execute("PRAGMA journal_mode = WAL")
            
            g.db = conn
            
        except sqlite3.Error as e:
            try:
                current_app.logger.error(f"Database connection error: {e}")
            except RuntimeError:
                logger.error(f"Database connection error: {e}")
            raise
    
    return g.db


def close_db(exception=None):
    """Close the database connection when the request context ends."""
    db = g.pop('db', None)
    if db is not None:
        try:
            # Check if there are any pending transactions
            if db.total_changes > 0:
                # Log but don't auto-commit - should be handled by application
                pass
            db.close()
        except Exception as e:
            try:
                current_app.logger.warning(f"Error closing database: {e}")
            except RuntimeError:
                logger.warning(f"Error closing database: {e}")


# ============================================
# TRANSACTION HELPERS
# ============================================

class transaction:
    """
    Context manager for database transactions with automatic commit/rollback.
    Enhanced with retry logic for lock conflicts.
    """
    
    def __init__(self, autocommit=True, max_retries=MAX_RETRIES):
        self.autocommit = autocommit
        self.max_retries = max_retries
        self.conn = None
        self.cursor = None
        self._attempts = 0
    
    def __enter__(self):
        self.conn = get_db()
        self.cursor = self.conn.cursor()
        return self.cursor
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.autocommit:
            if exc_type is None:
                # Success - commit
                try:
                    self.conn.commit()
                except sqlite3.OperationalError as e:
                    # Commit failed - rollback and re-raise
                    try:
                        self.conn.rollback()
                    except:
                        pass
                    raise
            else:
                # Error - rollback
                try:
                    self.conn.rollback()
                except:
                    pass
        self.cursor = None


def execute_with_retry(query, params=(), max_retries=MAX_RETRIES, commit=True, operation_name=None):
    """
    Execute a query with automatic retry on database lock errors.
    Uses exponential backoff with jitter.
    """
    if operation_name is None:
        operation_name = query[:50] + ('...' if len(query) > 50 else '')
    
    for attempt in range(max_retries):
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(query, params)
            if commit:
                conn.commit()
            return cursor
            
        except sqlite3.OperationalError as e:
            error_msg = str(e)
            
            if is_retryable_error(error_msg):
                if attempt < max_retries - 1:
                    delay = calculate_backoff(attempt)
                    # Add small jitter to prevent thundering herd
                    jitter = (time.time() % 0.1) * 0.05
                    wait_time = delay + jitter
                    
                    try:
                        current_app.logger.warning(
                            f"DB retry {attempt+1}/{max_retries} for {operation_name}: {error_msg} "
                            f"(waiting {wait_time:.3f}s)"
                        )
                    except RuntimeError:
                        logger.warning(
                            f"DB retry {attempt+1}/{max_retries} for {operation_name}: {error_msg} "
                            f"(waiting {wait_time:.3f}s)"
                        )
                    
                    time.sleep(wait_time)
                    continue
                raise
            
            # Non-retryable error
            try:
                conn = get_db()
                conn.rollback()
            except:
                pass
            raise
        
        except (sqlite3.IntegrityError, sqlite3.ProgrammingError) as e:
            # These are permanent errors - don't retry
            try:
                conn = get_db()
                conn.rollback()
            except:
                pass
            raise
        
        except Exception as e:
            # Unexpected error - rollback and raise
            try:
                conn = get_db()
                conn.rollback()
            except:
                pass
            raise
    
    # If we get here, all retries failed
    raise sqlite3.OperationalError(
        f"Database operation failed after {max_retries} retries: {operation_name}"
    )


def execute_many_with_retry(query, params_list, max_retries=MAX_RETRIES, operation_name=None):
    """
    Execute a query with multiple parameter sets in a single transaction.
    Enhanced with retry logic.
    """
    if not params_list:
        return None
    
    if operation_name is None:
        operation_name = query[:50] + ('...' if len(query) > 50 else '')
    
    for attempt in range(max_retries):
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            return cursor
            
        except sqlite3.OperationalError as e:
            error_msg = str(e)
            
            if is_retryable_error(error_msg):
                if attempt < max_retries - 1:
                    delay = calculate_backoff(attempt)
                    jitter = (time.time() % 0.1) * 0.05
                    wait_time = delay + jitter
                    
                    try:
                        current_app.logger.warning(
                            f"DB retry {attempt+1}/{max_retries} for {operation_name}: {error_msg} "
                            f"(waiting {wait_time:.3f}s)"
                        )
                    except RuntimeError:
                        logger.warning(
                            f"DB retry {attempt+1}/{max_retries} for {operation_name}: {error_msg} "
                            f"(waiting {wait_time:.3f}s)"
                        )
                    
                    time.sleep(wait_time)
                    continue
                raise
            
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
    
    raise sqlite3.OperationalError(
        f"Database operation failed after {max_retries} retries: {operation_name}"
    )


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
    return get_somali_time_db()


# ============================================
# PUBLIC ID GENERATION
# ============================================

PUBLIC_ID_CHARS = string.ascii_uppercase + '123456789'

def generate_public_id() -> str:
    return ''.join(secrets.choice(PUBLIC_ID_CHARS) for _ in range(4))

def get_student_by_public_id(public_id: str):
    cursor = execute_with_retry("SELECT * FROM students WHERE public_id = ?", (public_id,))
    result = cursor.fetchone()
    return dict(result) if result else None


# ============================================
# STUDENT FUNCTIONS
# ============================================

def get_student_by_phone(phone: str):
    cursor = execute_with_retry("SELECT * FROM students WHERE phone_number = ?", (phone,))
    result = cursor.fetchone()
    return dict(result) if result else None

def get_student_by_id(student_id: int):
    cursor = execute_with_retry("SELECT * FROM students WHERE id = ?", (student_id,))
    result = cursor.fetchone()
    return dict(result) if result else None

def create_student(data: dict):
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
        try:
            current_app.logger.error(f"Error creating student: {e}")
        except RuntimeError:
            logger.error(f"Error creating student: {e}")
        return None

def update_student_points(student_id: int, points: int):
    try:
        execute_with_retry(
            "UPDATE students SET total_points = ? WHERE id = ?",
            (points, student_id),
            commit=True
        )
        return get_student_by_id(student_id)
    except Exception as e:
        try:
            current_app.logger.error(f"Error updating points: {e}")
        except RuntimeError:
            logger.error(f"Error updating points: {e}")
        return None

def is_admin(user_id: int) -> bool:
    try:
        cursor = execute_with_retry("SELECT is_admin FROM students WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return bool(result['is_admin']) if result else False
    except Exception as e:
        try:
            current_app.logger.error(f"Error checking admin: {e}")
        except RuntimeError:
            logger.error(f"Error checking admin: {e}")
        return False

def toggle_admin(user_id: int):
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
        try:
            current_app.logger.error(f"Error toggling admin: {e}")
        except RuntimeError:
            logger.error(f"Error toggling admin: {e}")
        return None

def get_all_students():
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
        try:
            current_app.logger.error(f"Error fetching students: {e}")
        except RuntimeError:
            logger.error(f"Error fetching students: {e}")
        return []

def get_schools_by_location(location: str):
    try:
        cursor = execute_with_retry("SELECT * FROM schools WHERE location = ?", (location,))
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching schools: {e}")
        except RuntimeError:
            logger.error(f"Error fetching schools: {e}")
        return []


# ============================================
# SUBJECT FUNCTIONS
# ============================================

def get_all_subjects():
    try:
        cursor = execute_with_retry("SELECT * FROM subjects ORDER BY name")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching subjects: {e}")
        except RuntimeError:
            logger.error(f"Error fetching subjects: {e}")
        return []

def get_subject_by_id(subject_id: int):
    try:
        cursor = execute_with_retry("SELECT * FROM subjects WHERE id = ?", (subject_id,))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching subject: {e}")
        except RuntimeError:
            logger.error(f"Error fetching subject: {e}")
        return None

def get_subject_by_name(name: str):
    try:
        cursor = execute_with_retry("SELECT * FROM subjects WHERE LOWER(name) = LOWER(?)", (name,))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching subject: {e}")
        except RuntimeError:
            logger.error(f"Error fetching subject: {e}")
        return None

def create_subject(data: dict):
    try:
        execute_with_retry("""
            INSERT INTO subjects (name, icon)
            VALUES (?, ?)
        """, (data['name'], data.get('icon', '📚')), commit=True)
        return get_subject_by_name(data['name'])
    except Exception as e:
        try:
            current_app.logger.error(f"Error creating subject: {e}")
        except RuntimeError:
            logger.error(f"Error creating subject: {e}")
        return None

def delete_subject(subject_id: int):
    try:
        execute_with_retry("DELETE FROM subjects WHERE id = ?", (subject_id,), commit=True)
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error deleting subject: {e}")
        except RuntimeError:
            logger.error(f"Error deleting subject: {e}")
        return False


# ============================================
# QUESTION FUNCTIONS
# ============================================

def get_questions_by_subject(subject_id: int, limit: int = 10):
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
        try:
            current_app.logger.error(f"Error fetching questions: {e}")
        except RuntimeError:
            logger.error(f"Error fetching questions: {e}")
        return []

def get_all_questions():
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
            q['subject'] = {'name': q.pop('subject_name', '')} if q.get('subject_name') else None
            questions.append(q)
        return questions
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching questions: {e}")
        except RuntimeError:
            logger.error(f"Error fetching questions: {e}")
        return []

def create_question(data: dict):
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
        try:
            current_app.logger.error(f"Error creating question: {e}")
        except RuntimeError:
            logger.error(f"Error creating question: {e}")
        return False


def bulk_create_questions(questions_data: list, admin_id: int):
    """
    Bulk import questions with transaction safety and progress reporting.
    Uses pre-validation and batch inserts with rollback on error.
    """
    imported_count = 0
    errors = []
    total = len(questions_data)
    
    if total == 0:
        return {'imported': 0, 'errors': [], 'total': 0}
    
    try:
        # ============================================
        # PHASE 1: PRE-VALIDATE ALL QUESTIONS
        # ============================================
        
        valid_questions = []
        validation_errors = []
        
        for idx, q in enumerate(questions_data, 1):
            # Validate required fields
            if not q.get('question_text', '').strip():
                validation_errors.append({
                    'index': idx,
                    'question': 'Unknown',
                    'error': 'Question text is required'
                })
                continue
            
            if not q.get('options') or len(q['options']) < 3:
                validation_errors.append({
                    'index': idx,
                    'question': q.get('question_text', 'Unknown')[:50],
                    'error': 'Minimum 3 options required'
                })
                continue
            
            if len(q['options']) > 6:
                validation_errors.append({
                    'index': idx,
                    'question': q.get('question_text', 'Unknown')[:50],
                    'error': 'Maximum 6 options allowed'
                })
                continue
            
            if not q.get('correct_answer'):
                validation_errors.append({
                    'index': idx,
                    'question': q.get('question_text', 'Unknown')[:50],
                    'error': 'Correct answer is required'
                })
                continue
            
            valid_questions.append(q)
        
        # If there are validation errors, return them without importing
        if validation_errors:
            return {
                'imported': 0,
                'errors': validation_errors,
                'total': total,
                'validation_failed': True
            }
        
        # ============================================
        # PHASE 2: BATCH INSERT WITH TRANSACTIONS
        # ============================================
        
        batch_size = BULK_INSERT_BATCH_SIZE
        total_valid = len(valid_questions)
        
        for i in range(0, total_valid, batch_size):
            batch = valid_questions[i:i + batch_size]
            batch_start = i + 1
            batch_end = min(i + batch_size, total_valid)
            
            try:
                # Start a transaction for this batch
                conn = get_db()
                cursor = conn.cursor()
                
                # Prepare batch data
                batch_params = []
                for q in batch:
                    batch_params.append((
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
                
                # Execute batch insert
                cursor.executemany("""
                    INSERT INTO questions (
                        subject_id, question_text, options, correct_answer,
                        difficulty, chapter, tags, explanation,
                        created_by, updated_by, status, version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch_params)
                
                # Commit the batch
                conn.commit()
                imported_count += len(batch)
                
                try:
                    current_app.logger.info(
                        f"Bulk import: Batch {batch_start}-{batch_end} of {total_valid} "
                        f"completed ({imported_count}/{total_valid} total)"
                    )
                except RuntimeError:
                    logger.info(
                        f"Bulk import: Batch {batch_start}-{batch_end} of {total_valid} "
                        f"completed ({imported_count}/{total_valid} total)"
                    )
                
            except Exception as e:
                # Rollback the failed batch
                try:
                    get_db().rollback()
                except:
                    pass
                
                error_msg = str(e)
                try:
                    current_app.logger.error(
                        f"Bulk import batch {batch_start}-{batch_end} failed: {error_msg}"
                    )
                except RuntimeError:
                    logger.error(
                        f"Bulk import batch {batch_start}-{batch_end} failed: {error_msg}"
                    )
                
                # Add batch errors
                for idx, q in enumerate(batch, start=batch_start):
                    errors.append({
                        'index': idx,
                        'question': q.get('question_text', 'Unknown')[:50],
                        'error': f'Batch insert failed: {error_msg}'
                    })
                
                # Continue with next batch? 
                # We continue to import as many as possible
                continue
        
        return {
            'imported': imported_count,
            'errors': errors,
            'total': total,
            'validation_failed': False
        }
        
    except Exception as e:
        try:
            current_app.logger.error(f"Bulk import failed: {e}", exc_info=True)
        except RuntimeError:
            logger.error(f"Bulk import failed: {e}", exc_info=True)
        
        return {
            'imported': imported_count,
            'errors': [{'error': str(e), 'question': 'Fatal error'}],
            'total': total,
            'validation_failed': True
        }


def update_question(question_id: int, data: dict):
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
        try:
            current_app.logger.error(f"Error updating question: {e}")
        except RuntimeError:
            logger.error(f"Error updating question: {e}")
        return False

def delete_question(question_id: int):
    try:
        execute_with_retry(
            "UPDATE questions SET status = 'archived' WHERE id = ?",
            (question_id,),
            commit=True
        )
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error deleting question: {e}")
        except RuntimeError:
            logger.error(f"Error deleting question: {e}")
        return False

def get_question_by_id(question_id: int):
    try:
        cursor = execute_with_retry("SELECT * FROM questions WHERE id = ?", (question_id,))
        result = cursor.fetchone()
        if result:
            q = dict(result)
            q['options'] = from_json(q['options'])
            return q
        return None
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching question: {e}")
        except RuntimeError:
            logger.error(f"Error fetching question: {e}")
        return None

def check_question_exists(question_text: str, subject_id: int):
    try:
        cursor = execute_with_retry(
            "SELECT id FROM questions WHERE LOWER(question_text) = LOWER(?) AND subject_id = ? AND status = 'active'",
            (question_text, subject_id)
        )
        result = cursor.fetchone()
        return result is not None
    except Exception as e:
        try:
            current_app.logger.error(f"Error checking question: {e}")
        except RuntimeError:
            logger.error(f"Error checking question: {e}")
        return False


# ============================================
# QUIZ ATTEMPT FUNCTIONS
# ============================================

def save_quiz_attempt(student_id: int, subject_id: int, score: int, total: int, answers: list, ratings: list):
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
        try:
            current_app.logger.error(f"Error saving quiz attempt: {e}")
        except RuntimeError:
            logger.error(f"Error saving quiz attempt: {e}")
        return None

def get_user_quiz_history(student_id: int, limit: int = 10):
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
            a['subject'] = {'name': a.pop('subject_name', '')} if a.get('subject_name') else None
            a['answers'] = from_json(a['answers'])
            a['ratings'] = from_json(a['ratings'])
            attempts.append(a)
        return attempts
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching quiz history: {e}")
        except RuntimeError:
            logger.error(f"Error fetching quiz history: {e}")
        return []

def get_leaderboard(limit: int = 20):
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
        try:
            current_app.logger.error(f"Error fetching leaderboard: {e}")
        except RuntimeError:
            logger.error(f"Error fetching leaderboard: {e}")
        return []


# ============================================
# DELETED USERS FUNCTIONS
# ============================================

def delete_user(student_id: int, admin_id: int, keep_ratings: bool = True, delete_attempts: bool = True):
    try:
        user = get_student_by_id(student_id)
        if not user:
            return None, 'User not found'
        
        if student_id == admin_id:
            return None, 'You cannot delete your own account'
        
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
        try:
            current_app.logger.error(f"Error deleting user: {e}")
        except RuntimeError:
            logger.error(f"Error deleting user: {e}")
        return False, str(e)

def get_deleted_users(limit: int = 50):
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
        try:
            current_app.logger.error(f"Error fetching deleted users: {e}")
        except RuntimeError:
            logger.error(f"Error fetching deleted users: {e}")
        return []

def restore_deleted_user(deleted_id: int):
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
        try:
            current_app.logger.error(f"Error restoring user: {e}")
        except RuntimeError:
            logger.error(f"Error restoring user: {e}")
        return False, str(e)


# ============================================
# GROUP FUNCTIONS
# ============================================

def get_all_groups():
    try:
        cursor = execute_with_retry("SELECT * FROM groups ORDER BY created_at DESC")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching groups: {e}")
        except RuntimeError:
            logger.error(f"Error fetching groups: {e}")
        return []

def get_active_groups():
    try:
        cursor = execute_with_retry("SELECT * FROM groups WHERE is_active = 1 ORDER BY created_at DESC")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching groups: {e}")
        except RuntimeError:
            logger.error(f"Error fetching groups: {e}")
        return []

def create_group(data: dict):
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
        try:
            current_app.logger.error(f"Error creating group: {e}")
        except RuntimeError:
            logger.error(f"Error creating group: {e}")
        return False

def delete_group(group_id: int):
    try:
        execute_with_retry("DELETE FROM groups WHERE id = ?", (group_id,), commit=True)
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error deleting group: {e}")
        except RuntimeError:
            logger.error(f"Error deleting group: {e}")
        return False

def track_group_click(group_id: int):
    try:
        execute_with_retry(
            "UPDATE groups SET click_count = click_count + 1 WHERE id = ?",
            (group_id,),
            commit=True
        )
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error tracking group click: {e}")
        except RuntimeError:
            logger.error(f"Error tracking group click: {e}")
        return False

def get_group_by_id(group_id: int):
    try:
        cursor = execute_with_retry("SELECT * FROM groups WHERE id = ?", (group_id,))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching group: {e}")
        except RuntimeError:
            logger.error(f"Error fetching group: {e}")
        return None


# ============================================
# PDF FUNCTIONS
# ============================================

def get_all_pdfs():
    try:
        cursor = execute_with_retry("SELECT * FROM pdfs ORDER BY created_at DESC")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching PDFs: {e}")
        except RuntimeError:
            logger.error(f"Error fetching PDFs: {e}")
        return []

def get_pdf_by_id(pdf_id: int):
    try:
        cursor = execute_with_retry("SELECT * FROM pdfs WHERE id = ?", (pdf_id,))
        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching PDF: {e}")
        except RuntimeError:
            logger.error(f"Error fetching PDF: {e}")
        return None

def create_pdf(data: dict):
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
        try:
            current_app.logger.error(f"Error creating PDF: {e}")
        except RuntimeError:
            logger.error(f"Error creating PDF: {e}")
        return False

def delete_pdf(pdf_id: int):
    try:
        execute_with_retry("DELETE FROM pdfs WHERE id = ?", (pdf_id,), commit=True)
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error deleting PDF: {e}")
        except RuntimeError:
            logger.error(f"Error deleting PDF: {e}")
        return False

def increment_pdf_view(pdf_id: int):
    try:
        execute_with_retry(
            "UPDATE pdfs SET view_count = view_count + 1 WHERE id = ?",
            (pdf_id,),
            commit=True
        )
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error incrementing PDF view: {e}")
        except RuntimeError:
            logger.error(f"Error incrementing PDF view: {e}")
        return False

def get_pdf_distinct_subjects():
    try:
        cursor = execute_with_retry("SELECT DISTINCT subject FROM pdfs WHERE subject IS NOT NULL AND subject != ''")
        results = cursor.fetchall()
        return [row['subject'] for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching PDF subjects: {e}")
        except RuntimeError:
            logger.error(f"Error fetching PDF subjects: {e}")
        return []

def get_pdf_distinct_grades():
    try:
        cursor = execute_with_retry("SELECT DISTINCT grade FROM pdfs WHERE grade IS NOT NULL AND grade != ''")
        results = cursor.fetchall()
        return [row['grade'] for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching PDF grades: {e}")
        except RuntimeError:
            logger.error(f"Error fetching PDF grades: {e}")
        return []

def search_pdfs(search: str = '', subject: str = '', grade: str = ''):
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
        try:
            current_app.logger.error(f"Error searching PDFs: {e}")
        except RuntimeError:
            logger.error(f"Error searching PDFs: {e}")
        return []


# ============================================
# LIVE QUIZ FUNCTIONS
# ============================================

def create_live_quiz(data: dict):
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
        try:
            current_app.logger.error(f"Error creating live quiz: {e}")
        except RuntimeError:
            logger.error(f"Error creating live quiz: {e}")
        return None

def get_live_quiz_by_id(quiz_id: int):
    try:
        cursor = execute_with_retry("SELECT * FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            return quiz
        return None
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching live quiz: {e}")
        except RuntimeError:
            logger.error(f"Error fetching live quiz: {e}")
        return None

def get_live_quiz_by_code(join_code: str):
    try:
        cursor = execute_with_retry("SELECT * FROM live_quizzes WHERE join_code = ?", (join_code,))
        result = cursor.fetchone()
        if result:
            quiz = dict(result)
            quiz['question_ids'] = from_json(quiz['question_ids'])
            return quiz
        return None
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching live quiz: {e}")
        except RuntimeError:
            logger.error(f"Error fetching live quiz: {e}")
        return None

def get_live_quiz_with_subject(quiz_id: int):
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
        try:
            current_app.logger.error(f"Error fetching live quiz: {e}")
        except RuntimeError:
            logger.error(f"Error fetching live quiz: {e}")
        return None

def update_live_quiz(quiz_id: int, data: dict):
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
        try:
            current_app.logger.error(f"Error updating live quiz: {e}")
        except RuntimeError:
            logger.error(f"Error updating live quiz: {e}")
        return False

def get_live_quiz_participants(quiz_id: int):
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
        try:
            current_app.logger.error(f"Error fetching participants: {e}")
        except RuntimeError:
            logger.error(f"Error fetching participants: {e}")
        return []

def get_live_quiz_participant(quiz_id: int, student_id: int):
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
        try:
            current_app.logger.error(f"Error fetching participant: {e}")
        except RuntimeError:
            logger.error(f"Error fetching participant: {e}")
        return None

def add_live_quiz_participant(quiz_id: int, student_id: int):
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
        try:
            current_app.logger.error(f"Error adding participant: {e}")
        except RuntimeError:
            logger.error(f"Error adding participant: {e}")
        return False

def update_live_quiz_participant(participant_id: int, data: dict):
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
        try:
            current_app.logger.error(f"Error updating participant: {e}")
        except RuntimeError:
            logger.error(f"Error updating participant: {e}")
        return False

def get_live_quiz_participants_with_names(quiz_id: int):
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
        try:
            current_app.logger.error(f"Error fetching participants: {e}")
        except RuntimeError:
            logger.error(f"Error fetching participants: {e}")
        return []

def get_active_live_quiz(join_code: str):
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
        try:
            current_app.logger.error(f"Error fetching active quiz: {e}")
        except RuntimeError:
            logger.error(f"Error fetching active quiz: {e}")
        return None

def get_live_quiz_count(quiz_id: int):
    try:
        cursor = execute_with_retry(
            "SELECT COUNT(*) as count FROM live_quiz_participants WHERE quiz_id = ?",
            (quiz_id,)
        )
        result = cursor.fetchone()
        return result['count'] if result else 0
    except Exception as e:
        try:
            current_app.logger.error(f"Error getting participant count: {e}")
        except RuntimeError:
            logger.error(f"Error getting participant count: {e}")
        return 0

def get_live_quiz_completed_count(quiz_id: int):
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
        try:
            current_app.logger.error(f"Error getting completed count: {e}")
        except RuntimeError:
            logger.error(f"Error getting completed count: {e}")
        return 0

def get_question_ids_for_quiz(quiz_id: int):
    try:
        cursor = execute_with_retry("SELECT question_ids FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        if result:
            return from_json(result['question_ids'])
        return []
    except Exception as e:
        try:
            current_app.logger.error(f"Error getting question IDs: {e}")
        except RuntimeError:
            logger.error(f"Error getting question IDs: {e}")
        return []

def get_questions_by_ids(question_ids: list):
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
        try:
            current_app.logger.error(f"Error fetching questions by IDs: {e}")
        except RuntimeError:
            logger.error(f"Error fetching questions by IDs: {e}")
        return []

def update_participant_rankings(quiz_id: int):
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
        try:
            current_app.logger.error(f"Error updating rankings: {e}")
        except RuntimeError:
            logger.error(f"Error updating rankings: {e}")
        return False

def get_live_quiz_creator_id(quiz_id: int):
    try:
        cursor = execute_with_retry("SELECT creator_id FROM live_quizzes WHERE id = ?", (quiz_id,))
        result = cursor.fetchone()
        return result['creator_id'] if result else None
    except Exception as e:
        try:
            current_app.logger.error(f"Error getting creator ID: {e}")
        except RuntimeError:
            logger.error(f"Error getting creator ID: {e}")
        return None

def get_group_categories():
    try:
        cursor = execute_with_retry("""
            SELECT DISTINCT category FROM groups 
            WHERE category IS NOT NULL AND category != '' AND is_active = 1
        """)
        results = cursor.fetchall()
        return [row['category'] for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching group categories: {e}")
        except RuntimeError:
            logger.error(f"Error fetching group categories: {e}")
        return []

def search_groups(search: str = '', platform: str = '', category: str = ''):
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
        try:
            current_app.logger.error(f"Error searching groups: {e}")
        except RuntimeError:
            logger.error(f"Error searching groups: {e}")
        return []


# ============================================
# NOTIFICATION FUNCTIONS
# ============================================

def create_notification(user_id, type, title, body, link='', icon=''):
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
        try:
            current_app.logger.error(f"Error creating notification: {e}")
        except RuntimeError:
            logger.error(f"Error creating notification: {e}")
        return False

def create_notification_for_all_users(type, title, body, link='', icon=''):
    try:
        cursor = execute_with_retry("SELECT id FROM students")
        users = cursor.fetchall()
        
        for user in users:
            create_notification(user['id'], type, title, body, link, icon)
        
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error creating notifications for all users: {e}")
        except RuntimeError:
            logger.error(f"Error creating notifications for all users: {e}")
        return False

def get_user_notifications(user_id, limit=20, unread_only=False):
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
        try:
            current_app.logger.error(f"Error getting notifications: {e}")
        except RuntimeError:
            logger.error(f"Error getting notifications: {e}")
        return []

def get_unread_count(user_id):
    try:
        cursor = execute_with_retry(
            "SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0",
            (user_id,)
        )
        result = cursor.fetchone()
        return result['count'] if result else 0
    except Exception as e:
        try:
            current_app.logger.error(f"Error getting unread count: {e}")
        except RuntimeError:
            logger.error(f"Error getting unread count: {e}")
        return 0

def mark_notification_read(notification_id, user_id):
    try:
        execute_with_retry("""
            UPDATE notifications 
            SET is_read = 1, read_at = ?
            WHERE id = ? AND user_id = ?
        """, (now(), notification_id, user_id), commit=True)
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error marking notification read: {e}")
        except RuntimeError:
            logger.error(f"Error marking notification read: {e}")
        return False

def mark_all_notifications_read(user_id):
    try:
        execute_with_retry("""
            UPDATE notifications 
            SET is_read = 1, read_at = ?
            WHERE user_id = ? AND is_read = 0
        """, (now(), user_id), commit=True)
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error marking all notifications read: {e}")
        except RuntimeError:
            logger.error(f"Error marking all notifications read: {e}")
        return False


# ============================================
# NOTIFICATION TRIGGERS
# ============================================

def notify_quiz_completed(user_id, subject_name, score, total):
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
        # Ensure directory exists
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_autocheckpoint = 1000")
        conn.execute(f"PRAGMA busy_timeout = {Config.DB_BUSY_TIMEOUT}")
        
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        if os.path.exists(schema_path):
            with open(schema_path, 'r') as f:
                schema = f.read()
            conn.executescript(schema)
            conn.commit()
            logger.info("Database initialized successfully")
            
            _create_optimization_indexes(conn)
        else:
            logger.warning(f"Schema file not found: {schema_path}")
        
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False


def _create_optimization_indexes(conn):
    """Create additional indexes for performance optimization."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_live_quiz_participants_quiz_score ON live_quiz_participants(quiz_id, score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read)",
        "CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student_completed ON quiz_attempts(student_id, completed_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_live_quizzes_status_created ON live_quizzes(status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_questions_subject_status ON questions(subject_id, status)",
    ]
    
    for idx in indexes:
        try:
            conn.execute(idx)
        except Exception as e:
            logger.warning(f"Error creating index {idx}: {e}")
    
    conn.commit()


def close_db_connections():
    """Legacy function for compatibility."""
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass


def ensure_wal_mode():
    """Ensure the database is in WAL mode."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_autocheckpoint = 1000")
        conn.execute(f"PRAGMA busy_timeout = {Config.DB_BUSY_TIMEOUT}")
        
        _create_optimization_indexes(conn)
        
        conn.close()
        logger.info("WAL mode enabled successfully")
        return True
    except Exception as e:
        logger.error(f"Error enabling WAL mode: {e}")
        return False


def check_database_integrity():
    """
    Check database integrity.
    Returns (is_healthy, error_message)
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        conn.close()
        if result and result[0] == 'ok':
            return True, None
        return False, result[0] if result else "unknown error"
    except Exception as e:
        return False, str(e)


# ============================================
# LIVE QUIZ LOBBY FUNCTIONS
# ============================================

def get_live_quizzes_lobby(
    user_id: int = None,
    status_filter: str = None,
    subject_filter: int = None,
    search: str = None,
    page: int = 1,
    per_page: int = 20
) -> tuple:
    """
    Get all public live quizzes for the lobby.
    Returns: (quizzes, total_count)
    """
    try:
        # Build the query
        query = """
            SELECT 
                lq.id,
                lq.title,
                lq.subject_id,
                lq.question_count,
                lq.status,
                lq.max_participants,
                lq.time_per_question,
                lq.created_at,
                lq.started_at,
                lq.ended_at,
                lq.join_code,
                lq.creator_id,
                lq.is_public,
                s.name as subject_name,
                s.icon as subject_icon,
                COUNT(DISTINCT lqp.id) as participant_count,
                creator.first_name as creator_first_name,
                creator.last_name as creator_last_name,
                creator.public_id as creator_public_id,
                CASE WHEN EXISTS (
                    SELECT 1 FROM live_quiz_participants lqp2 
                    WHERE lqp2.quiz_id = lq.id AND lqp2.student_id = ?
                ) THEN 1 ELSE 0 END as is_participant,
                CASE WHEN lq.creator_id = ? THEN 1 ELSE 0 END as is_creator,
                (SELECT ranking FROM live_quiz_participants 
                 WHERE quiz_id = lq.id AND student_id = ?) as user_rank
            FROM live_quizzes lq
            LEFT JOIN subjects s ON lq.subject_id = s.id
            LEFT JOIN students creator ON lq.creator_id = creator.id
            LEFT JOIN live_quiz_participants lqp ON lq.id = lqp.quiz_id
            WHERE lq.is_public = 1
        """
        count_query = """
            SELECT COUNT(DISTINCT lq.id) as total
            FROM live_quizzes lq
            WHERE lq.is_public = 1
        """
        params = [user_id or 0, user_id or 0, user_id or 0]
        count_params = []

        # Apply filters
        if status_filter and status_filter in ['waiting', 'active', 'finished']:
            query += " AND lq.status = ?"
            count_query += " AND lq.status = ?"
            params.append(status_filter)
            count_params.append(status_filter)
        else:
            # Show all statuses
            query += " AND lq.status IN ('waiting', 'active', 'finished')"
            count_query += " AND lq.status IN ('waiting', 'active', 'finished')"

        if subject_filter:
            query += " AND lq.subject_id = ?"
            count_query += " AND lq.subject_id = ?"
            params.append(subject_filter)
            count_params.append(subject_filter)

        if search:
            search_pattern = f"%{search}%"
            query += " AND (lq.title LIKE ? OR creator.first_name LIKE ? OR creator.last_name LIKE ?)"
            count_query += " AND (lq.title LIKE ?)"
            params.extend([search_pattern, search_pattern, search_pattern])
            count_params.append(search_pattern)

        # Group and order
        query += """
            GROUP BY lq.id
            ORDER BY 
                CASE lq.status 
                    WHEN 'waiting' THEN 1 
                    WHEN 'active' THEN 2 
                    WHEN 'finished' THEN 3 
                END,
                lq.created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([per_page, (page - 1) * per_page])

        # Execute main query
        cursor = execute_with_retry(query, params)
        results = cursor.fetchall()

        # Get total count
        count_cursor = execute_with_retry(count_query, count_params)
        count_result = count_cursor.fetchone()
        total = count_result['total'] if count_result else 0

        quizzes = []
        for row in results:
            quiz = dict(row)
            # Calculate remaining time for active quizzes
            if quiz['status'] == 'active' and quiz['started_at']:
                try:
                    from datetime import datetime, timezone
                    total_duration = quiz['question_count'] * (quiz['time_per_question'] + 10)  # +10 for rating
                    if isinstance(quiz['started_at'], str):
                        started = datetime.fromisoformat(quiz['started_at'].replace('Z', '+00:00'))
                    else:
                        started = quiz['started_at']
                    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                    remaining = max(0, total_duration - elapsed)
                    quiz['remaining_seconds'] = int(remaining)
                except Exception:
                    quiz['remaining_seconds'] = 0
            else:
                quiz['remaining_seconds'] = 0

            quizzes.append(quiz)

        return quizzes, total

    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching lobby quizzes: {e}")
        except RuntimeError:
            logger.error(f"Error fetching lobby quizzes: {e}")
        return [], 0


def get_live_quiz_stats() -> dict:
    """Get stats for the lobby."""
    try:
        cursor = execute_with_retry("""
            SELECT 
                COUNT(CASE WHEN status = 'waiting' AND is_public = 1 THEN 1 END) as waiting_count,
                COUNT(CASE WHEN status = 'active' AND is_public = 1 THEN 1 END) as active_count,
                COUNT(CASE WHEN status = 'finished' AND is_public = 1 THEN 1 END) as finished_count,
                COUNT(CASE WHEN is_public = 1 THEN 1 END) as total_public,
                (SELECT COUNT(DISTINCT student_id) FROM live_quiz_participants 
                 WHERE quiz_id IN (SELECT id FROM live_quizzes WHERE is_public = 1)) as total_participants
            FROM live_quizzes
            WHERE is_public = 1
        """)
        result = cursor.fetchone()
        return dict(result) if result else {
            'waiting_count': 0,
            'active_count': 0,
            'finished_count': 0,
            'total_public': 0,
            'total_participants': 0
        }
    except Exception as e:
        try:
            current_app.logger.error(f"Error getting live quiz stats: {e}")
        except RuntimeError:
            logger.error(f"Error getting live quiz stats: {e}")
        return {
            'waiting_count': 0,
            'active_count': 0,
            'finished_count': 0,
            'total_public': 0,
            'total_participants': 0
        }


def can_join_live_quiz(quiz_id: int, user_id: int) -> tuple:
    """
    Check if a user can join a quiz.
    Returns: (can_join, reason)
    """
    try:
        quiz = get_live_quiz_by_id(quiz_id)
        if not quiz:
            return False, "Quiz not found"

        if not quiz.get('is_public', 1):
            return False, "This quiz is private"

        if quiz['status'] != 'waiting':
            return False, "This quiz is not open for joining"

        participant = get_live_quiz_participant(quiz_id, user_id)
        if participant:
            return True, "Already joined"

        participant_count = get_live_quiz_count(quiz_id)
        if participant_count >= quiz.get('max_participants', 50):
            return False, "Quiz is full"

        return True, "OK"

    except Exception as e:
        try:
            current_app.logger.error(f"Error checking join: {e}")
        except RuntimeError:
            logger.error(f"Error checking join: {e}")
        return False, str(e)


def get_all_subjects():
    """Get all subjects - already exists in db.py, but adding for completeness."""
    try:
        cursor = execute_with_retry("SELECT * FROM subjects ORDER BY name")
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        try:
            current_app.logger.error(f"Error fetching subjects: {e}")
        except RuntimeError:
            logger.error(f"Error fetching subjects: {e}")
        return []


# ============================================
# LIVE QUIZ LEAVE/REJOIN FUNCTIONS
# ============================================

def leave_live_quiz(quiz_id: int, student_id: int) -> bool:
    """
    Mark a participant as 'left' in a live quiz.
    Only allowed if quiz is waiting or active.
    """
    try:
        # Check if quiz is already finished
        quiz = get_live_quiz_by_id(quiz_id)
        if not quiz or quiz['status'] == 'finished':
            return False
        
        # Update status to 'left'
        execute_with_retry("""
            UPDATE live_quiz_participants 
            SET status = 'left' 
            WHERE quiz_id = ? AND student_id = ?
        """, (quiz_id, student_id), commit=True)
        
        # Update cache
        from quiz_cache import get_quiz_cache
        cache = get_quiz_cache()
        cache.update_participant(quiz_id, student_id, {'status': 'left'})
        
        return True
    except Exception as e:
        logger.error(f"Error leaving quiz: {e}")
        return False


def rejoin_live_quiz(quiz_id: int, student_id: int) -> bool:
    """
    Reactivate a participant who previously left.
    Only allowed if quiz is waiting.
    """
    try:
        quiz = get_live_quiz_by_id(quiz_id)
        if not quiz or quiz['status'] != 'waiting':
            return False
        
        # Check if participant exists with status 'left'
        participant = get_live_quiz_participant(quiz_id, student_id)
        if not participant or participant['status'] != 'left':
            return False
        
        # Reset progress and set status to 'active'
        execute_with_retry("""
            UPDATE live_quiz_participants 
            SET status = 'active',
                score = 0,
                current_question_index = 0,
                correct_count = 0,
                wrong_count = 0,
                skipped_count = 0,
                answers = '{}',
                ratings = '{}'
            WHERE quiz_id = ? AND student_id = ?
        """, (quiz_id, student_id), commit=True)
        
        # Update cache
        from quiz_cache import get_quiz_cache
        cache = get_quiz_cache()
        cache.update_participant(quiz_id, student_id, {
            'status': 'active',
            'score': 0,
            'current_question_index': 0,
            'correct_count': 0,
            'wrong_count': 0,
            'skipped_count': 0,
            'answers': {},
            'ratings': {}
        })
        
        return True
    except Exception as e:
        logger.error(f"Error rejoining quiz: {e}")
        return False


def get_active_participants(quiz_id: int) -> list:
    """Get only active participants (status = 'active' or 'completed')."""
    try:
        cursor = execute_with_retry("""
            SELECT lqp.*, s.first_name, s.last_name, s.public_id
            FROM live_quiz_participants lqp
            LEFT JOIN students s ON lqp.student_id = s.id
            WHERE lqp.quiz_id = ? AND lqp.status IN ('active', 'completed')
            ORDER BY lqp.joined_at
        """, (quiz_id,))
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Error getting active participants: {e}")
        return []

# ============================================
# DELETE LIVE QUIZ FUNCTION
# ============================================

def delete_live_quiz(quiz_id: int) -> bool:
    """Delete a live quiz and all its participants."""
    try:
        # Delete participants first (cascade will handle, but explicit for safety)
        execute_with_retry("DELETE FROM live_quiz_participants WHERE quiz_id = ?", (quiz_id,), commit=True)
        execute_with_retry("DELETE FROM live_quizzes WHERE id = ?", (quiz_id,), commit=True)
        return True
    except Exception as e:
        logger.error(f"Error deleting live quiz {quiz_id}: {e}")
        return False