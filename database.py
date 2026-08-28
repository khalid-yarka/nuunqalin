# ============================================
# DATABASE VERIFICATION & MANAGEMENT
# ============================================
# Handles database startup, verification, and maintenance
# ============================================

import os
import sqlite3
import time
import logging
import fcntl
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from config import Config

logger = logging.getLogger(__name__)

# ============================================
# CONSTANTS
# ============================================

REQUIRED_TABLES = [
    'students',
    'subjects',
    'questions',
    'quiz_attempts',
    'groups',
    'pdfs',
    'live_quizzes',
    'live_quiz_participants',
    'deleted_users',
    'quiz_ratings',
    'notifications',
    'notification_preferences'
]

REQUIRED_COLUMNS = {
    'students': ['id', 'public_id', 'phone_number', 'password', 'first_name', 'last_name', 'is_admin', 'created_at'],
    'subjects': ['id', 'name', 'icon', 'created_at'],
    'questions': ['id', 'subject_id', 'question_text', 'options', 'correct_answer', 'difficulty', 'status', 'created_at'],
    'quiz_attempts': ['id', 'student_id', 'subject_id', 'score', 'total_questions', 'answers', 'ratings', 'completed_at'],
    'groups': ['id', 'name', 'platform', 'invite_link', 'is_active', 'created_at'],
    'pdfs': ['id', 'title', 'file_url', 'telegram_download_url', 'view_count', 'created_at'],
    'live_quizzes': ['id', 'creator_id', 'join_code', 'status', 'question_count', 'created_at'],
    'live_quiz_participants': ['id', 'quiz_id', 'student_id', 'score', 'answers', 'ratings', 'ranking'],
    'deleted_users': ['id', 'original_id', 'first_name', 'last_name', 'phone_number', 'data', 'deleted_at'],
    'quiz_ratings': ['id', 'student_id', 'question_id', 'rating', 'created_at'],
    'notifications': ['id', 'user_id', 'type', 'title', 'body', 'is_read', 'created_at'],
    'notification_preferences': ['id', 'user_id', 'notification_type', 'enabled', 'created_at']
}

DB_INIT_LOCK_FILE = os.path.join(os.path.dirname(Config.DATABASE_PATH), '.db_init_lock')


# ============================================
# DATABASE LOCK FOR STARTUP
# ============================================

def acquire_db_init_lock(timeout: int = 30) -> Optional[int]:
    """
    Acquire an exclusive lock for database initialization.
    Returns file descriptor if successful, None otherwise.
    """
    try:
        lock_dir = os.path.dirname(DB_INIT_LOCK_FILE)
        if lock_dir and not os.path.exists(lock_dir):
            os.makedirs(lock_dir, exist_ok=True)
        
        fd = open(DB_INIT_LOCK_FILE, 'w')
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fd.write(str(os.getpid()))
                fd.flush()
                return fd.fileno()
            except (IOError, OSError):
                time.sleep(0.5)
        return None
    except Exception as e:
        logger.error(f"Failed to acquire DB init lock: {e}")
        return None


def release_db_init_lock(fd: int) -> None:
    """Release the database initialization lock."""
    if fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception as e:
            logger.warning(f"Failed to release DB init lock: {e}")
        finally:
            try:
                fd.close()
            except:
                pass


# ============================================
# DATABASE CONNECTION HELPER
# ============================================

def _get_connection(db_path: str = None, timeout: int = 10):
    """Get a direct database connection."""
    if db_path is None:
        db_path = Config.DATABASE_PATH
    
    try:
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA busy_timeout = {Config.DB_BUSY_TIMEOUT}")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise


# ============================================
# DATABASE VERIFICATION FUNCTIONS
# ============================================

def get_schema_version(conn: sqlite3.Connection) -> Optional[str]:
    """Get the current schema version from the database."""
    try:
        cursor = conn.execute("PRAGMA user_version")
        result = cursor.fetchone()
        return str(result[0]) if result else None
    except Exception:
        return None


def verify_database_exists() -> bool:
    """Check if the database file exists."""
    return os.path.exists(Config.DATABASE_PATH)


def verify_database_openable() -> Tuple[bool, Optional[str]]:
    """Check if the database can be opened."""
    try:
        conn = _get_connection(timeout=5)
        conn.close()
        return True, None
    except Exception as e:
        return False, str(e)


def verify_database_integrity() -> Tuple[bool, Optional[str]]:
    """Run PRAGMA integrity_check on the database."""
    try:
        conn = _get_connection(timeout=10)
        cursor = conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] == 'ok':
            return True, None
        return False, result[0] if result else "unknown integrity error"
    except Exception as e:
        return False, str(e)


def verify_wal_enabled() -> Tuple[bool, Optional[str]]:
    """Check if WAL mode is enabled."""
    try:
        conn = _get_connection(timeout=5)
        cursor = conn.execute("PRAGMA journal_mode")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0].upper() == 'WAL':
            return True, None
        return False, f"WAL not enabled: {result[0] if result else 'unknown'}"
    except Exception as e:
        return False, str(e)


def verify_database_writable() -> Tuple[bool, Optional[str]]:
    """Check if the database is writable."""
    try:
        conn = _get_connection(timeout=5)
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _write_test (id INTEGER)")
        conn.execute("INSERT INTO _write_test (id) VALUES (1)")
        conn.execute("DELETE FROM _write_test WHERE id = 1")
        conn.execute("DROP TABLE _write_test")
        conn.commit()
        conn.close()
        return True, None
    except Exception as e:
        return False, str(e)


def verify_tables_exist(conn: sqlite3.Connection) -> Tuple[bool, List[str]]:
    """Verify all required tables exist."""
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {row[0] for row in cursor.fetchall()}
        
        missing_tables = [t for t in REQUIRED_TABLES if t not in existing_tables]
        return len(missing_tables) == 0, missing_tables
    except Exception as e:
        return False, [f"Error checking tables: {e}"]


def verify_columns_exist(conn: sqlite3.Connection) -> Tuple[bool, Dict[str, List[str]]]:
    """Verify all required columns exist in each table."""
    try:
        missing_columns = {}
        
        for table, required_cols in REQUIRED_COLUMNS.items():
            cursor = conn.execute(f"PRAGMA table_info({table})")
            existing_cols = {row[1] for row in cursor.fetchall()}
            
            missing = [c for c in required_cols if c not in existing_cols]
            if missing:
                missing_columns[table] = missing
        
        return len(missing_columns) == 0, missing_columns
    except Exception as e:
        return False, {"error": [f"Error checking columns: {e}"]}


# ============================================
# DATABASE INITIALIZATION
# ============================================

def create_database_schema() -> Tuple[bool, Optional[str]]:
    """Create the database schema from schema.sql."""
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    
    if not os.path.exists(schema_path):
        return False, f"Schema file not found: {schema_path}"
    
    try:
        # Ensure directory exists
        db_dir = os.path.dirname(Config.DATABASE_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        conn = _get_connection()
        conn.execute("PRAGMA foreign_keys = ON")
        
        with open(schema_path, 'r') as f:
            schema = f.read()
        
        conn.executescript(schema)
        conn.commit()
        conn.close()
        
        return True, None
    except Exception as e:
        return False, str(e)


def enable_wal_mode() -> Tuple[bool, Optional[str]]:
    """Enable WAL mode on the database."""
    try:
        conn = _get_connection()
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_autocheckpoint = 1000")
        conn.execute(f"PRAGMA busy_timeout = {Config.DB_BUSY_TIMEOUT}")
        conn.commit()
        conn.close()
        return True, None
    except Exception as e:
        return False, str(e)


# ============================================
# COMPLETE DATABASE VERIFICATION
# ============================================

def verify_database_full() -> Dict[str, Any]:
    """
    Perform a complete verification of the database.
    Returns a dict with all check results.
    """
    results = {
        'exists': False,
        'openable': False,
        'writable': False,
        'integrity': False,
        'wal_enabled': False,
        'tables': {'ok': False, 'missing': []},
        'columns': {'ok': False, 'missing': {}},
        'schema_version': None,
        'errors': []
    }
    
    # Check if database exists
    results['exists'] = verify_database_exists()
    if not results['exists']:
        results['errors'].append("Database file does not exist")
        return results
    
    # Check if database can be opened
    openable, error = verify_database_openable()
    results['openable'] = openable
    if not openable:
        results['errors'].append(f"Cannot open database: {error}")
        return results
    
    # Check if database is writable
    writable, error = verify_database_writable()
    results['writable'] = writable
    if not writable:
        results['errors'].append(f"Database not writable: {error}")
        return results
    
    try:
        conn = _get_connection()
        
        # Check schema version
        results['schema_version'] = get_schema_version(conn)
        
        # Check tables
        tables_ok, missing_tables = verify_tables_exist(conn)
        results['tables']['ok'] = tables_ok
        results['tables']['missing'] = missing_tables
        if not tables_ok:
            results['errors'].append(f"Missing tables: {', '.join(missing_tables)}")
        
        # Check columns
        columns_ok, missing_columns = verify_columns_exist(conn)
        results['columns']['ok'] = columns_ok
        results['columns']['missing'] = missing_columns
        if not columns_ok:
            for table, cols in missing_columns.items():
                results['errors'].append(f"Missing columns in {table}: {', '.join(cols)}")
        
        conn.close()
        
    except Exception as e:
        results['errors'].append(f"Error during table verification: {e}")
        return results
    
    # Check integrity
    integrity_ok, error = verify_database_integrity()
    results['integrity'] = integrity_ok
    if not integrity_ok:
        results['errors'].append(f"Integrity check failed: {error}")
    
    # Check WAL
    wal_ok, error = verify_wal_enabled()
    results['wal_enabled'] = wal_ok
    if not wal_ok:
        results['errors'].append(f"WAL not enabled: {error}")
    
    return results


# ============================================
# STARTUP DATABASE INITIALIZATION
# ============================================

def initialize_database_startup() -> Tuple[bool, List[str]]:
    """
    Initialize the database on application startup.
    Returns (success, errors) where errors is a list of error messages.
    """
    errors = []
    
    # Acquire startup lock
    lock_fd = acquire_db_init_lock()
    if lock_fd is None:
        errors.append("Could not acquire database initialization lock")
        return False, errors
    
    try:
        # Check if database exists
        if not verify_database_exists():
            logger.info("Database not found. Creating new database...")
            success, error = create_database_schema()
            if not success:
                errors.append(f"Failed to create database schema: {error}")
                return False, errors
            
            success, error = enable_wal_mode()
            if not success:
                errors.append(f"Failed to enable WAL mode: {error}")
                return False, errors
            
            logger.info("Database created successfully")
        
        # Full verification
        logger.info("Verifying database...")
        results = verify_database_full()
        
        # Check for issues
        if results['errors']:
            errors.extend(results['errors'])
            return False, errors
        
        # Ensure WAL is enabled (try to enable if not)
        if not results['wal_enabled']:
            logger.warning("WAL not enabled, attempting to enable...")
            success, error = enable_wal_mode()
            if not success:
                errors.append(f"Failed to enable WAL mode: {error}")
                return False, errors
            logger.info("WAL mode enabled")
        
        logger.info("Database verification complete")
        return True, []
        
    except Exception as e:
        logger.error(f"Database initialization error: {e}", exc_info=True)
        errors.append(f"Unexpected error: {str(e)}")
        return False, errors
    finally:
        release_db_init_lock(lock_fd)


# ============================================
# DATABASE HEALTH CHECK (for /health endpoint)
# ============================================

def get_database_health() -> Dict[str, Any]:
    """
    Get detailed database health information.
    Used by the /health endpoint.
    """
    health = {
        'exists': False,
        'openable': False,
        'writable': False,
        'integrity': False,
        'wal_enabled': False,
        'tables_ok': False,
        'columns_ok': False,
        'errors': [],
        'details': {}
    }
    
    health['exists'] = verify_database_exists()
    if not health['exists']:
        health['errors'].append("Database does not exist")
        return health
    
    openable, error = verify_database_openable()
    health['openable'] = openable
    if not openable:
        health['errors'].append(f"Cannot open database: {error}")
        return health
    
    writable, error = verify_database_writable()
    health['writable'] = writable
    if not writable:
        health['errors'].append(f"Database not writable: {error}")
    
    try:
        conn = _get_connection()
        
        # Check tables
        tables_ok, missing = verify_tables_exist(conn)
        health['tables_ok'] = tables_ok
        health['details']['missing_tables'] = missing
        
        # Check columns
        columns_ok, missing_cols = verify_columns_exist(conn)
        health['columns_ok'] = columns_ok
        health['details']['missing_columns'] = missing_cols
        
        conn.close()
        
    except Exception as e:
        health['errors'].append(f"Table verification error: {e}")
    
    # Check integrity
    integrity_ok, error = verify_database_integrity()
    health['integrity'] = integrity_ok
    if not integrity_ok:
        health['errors'].append(f"Integrity check failed: {error}")
    
    # Check WAL
    wal_ok, error = verify_wal_enabled()
    health['wal_enabled'] = wal_ok
    if not wal_ok:
        health['errors'].append(f"WAL not enabled: {error}")
    
    return health