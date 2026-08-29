import os
from dotenv import load_dotenv
from datetime import timedelta
from pathlib import Path

load_dotenv()

# ============================================
# BASE DIRECTORY - Absolute Path Resolution
# ============================================

BASE_DIR = Path(__file__).resolve().parent

class Config:
    # ============================================
    # SECURITY
    # ============================================
    
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    ADMIN_ERROR_PASSWORD = os.getenv('ADMIN_ERROR_PASSWORD', '')
    
    # ============================================
    # DATABASE - Absolute Path
    # ============================================
    
    DATABASE_PATH = os.getenv('DATABASE_PATH')
    if DATABASE_PATH:
        if not os.path.isabs(DATABASE_PATH):
            DATABASE_PATH = str(BASE_DIR / DATABASE_PATH)
    else:
        DATABASE_PATH = str(BASE_DIR / 'nuunplatform.db')
    
    DB_TIMEOUT = float(os.getenv('DB_TIMEOUT', '30.0'))
    DB_BUSY_TIMEOUT = int(os.getenv('DB_BUSY_TIMEOUT', '30000'))
    DB_RETRY_ATTEMPTS = int(os.getenv('DB_RETRY_ATTEMPTS', '7'))
    DB_RETRY_INITIAL_DELAY = float(os.getenv('DB_RETRY_INITIAL_DELAY', '0.1'))
    DB_MAX_RETRY_DELAY = float(os.getenv('DB_MAX_RETRY_DELAY', '3.0'))
    DB_RETRY_BACKOFF_MULTIPLIER = float(os.getenv('DB_RETRY_BACKOFF_MULTIPLIER', '2.0'))
    
    # ============================================
    # SESSION — SECURE SETTINGS
    # ============================================
    
    SESSION_TYPE = 'filesystem'
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)
    
    # CRITICAL: Set these according to your deployment
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    ADMIN_SESSION_TIMEOUT = int(os.getenv('ADMIN_SESSION_TIMEOUT', '1800'))
    
    # ============================================
    # PATHS - Absolute
    # ============================================
    
    BACKUP_DIR = os.getenv('BACKUP_DIR')
    if BACKUP_DIR:
        if not os.path.isabs(BACKUP_DIR):
            BACKUP_DIR = str(BASE_DIR / BACKUP_DIR)
    else:
        BACKUP_DIR = str(BASE_DIR / 'BACKUPS')
    
    LOG_DIR = os.getenv('LOG_DIR')
    if LOG_DIR:
        if not os.path.isabs(LOG_DIR):
            LOG_DIR = str(BASE_DIR / LOG_DIR)
    else:
        LOG_DIR = str(BASE_DIR / 'logs')
    
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static/uploads/pdfs')
    if not os.path.isabs(UPLOAD_FOLDER):
        UPLOAD_FOLDER = str(BASE_DIR / UPLOAD_FOLDER)
    
    # ============================================
    # FILE UPLOADS
    # ============================================
    
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    
    # ============================================
    # BACKUP CONFIGURATION
    # ============================================
    
    BACKUP_ENABLED = os.getenv('BACKUP_ENABLED', 'true').lower() == 'true'
    BACKUP_TRIGGER_TOKEN = os.getenv('BACKUP_TRIGGER_TOKEN', 'change_this_token_in_production')
    BACKUP_RETENTION_DAILY = int(os.getenv('BACKUP_RETENTION_DAILY', '7'))
    BACKUP_RETENTION_WEEKLY = int(os.getenv('BACKUP_RETENTION_WEEKLY', '4'))
    BACKUP_RETENTION_MONTHLY = int(os.getenv('BACKUP_RETENTION_MONTHLY', '12'))
    
    # ============================================
    # QUIZ CONFIGURATION
    # ============================================
    
    RATING_TIME = int(os.getenv('RATING_TIME', '10'))
    LIVE_QUIZ_TIME_PER_QUESTION = int(os.getenv('LIVE_QUIZ_TIME_PER_QUESTION', '30'))
    LIVE_QUIZ_MAX_PARTICIPANTS = int(os.getenv('LIVE_QUIZ_MAX_PARTICIPANTS', '50'))
    
    # ============================================
    # RATE LIMITING
    # ============================================
    
    RATE_LIMIT_DEFAULT = os.getenv('RATE_LIMIT_DEFAULT', '200 per day;50 per hour')
    RATE_LIMIT_LOGIN = os.getenv('RATE_LIMIT_LOGIN', '5 per minute')
    RATE_LIMIT_ADMIN = os.getenv('RATE_LIMIT_ADMIN', '10 per minute')
    
    # ============================================
    # LOGGING
    # ============================================
    
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'WARNING')
    LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', str(10 * 1024 * 1024)))
    LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '5'))
    
    # ============================================
    # EMAIL CONFIGURATION
    # ============================================
    
    SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    SMTP_FROM = os.getenv('SMTP_FROM', '')
    SMTP_TO = os.getenv('SMTP_TO', '')
    
    EMAIL_ENABLED = bool(SMTP_USER and SMTP_PASSWORD and SMTP_TO)
    ERROR_EMAIL_DEDUP_WINDOW = int(os.getenv('ERROR_EMAIL_DEDUP_WINDOW', '300'))
    
    # ============================================
    # ERROR LOGGING
    # ============================================
    
    ERROR_RETENTION_DAYS = int(os.getenv('ERROR_RETENTION_DAYS', '30'))
    ERROR_LOG_SAMPLE_RATE = float(os.getenv('ERROR_LOG_SAMPLE_RATE', '1.0'))
    
    # ============================================
    # ENSURE DIRECTORIES EXIST
    # ============================================
    
    @classmethod
    def ensure_directories(cls):
        directories = [
            cls.BACKUP_DIR,
            cls.LOG_DIR,
            os.path.dirname(cls.UPLOAD_FOLDER),
            os.path.dirname(cls.DATABASE_PATH)
        ]
        for directory in directories:
            if directory and not os.path.exists(directory):
                try:
                    os.makedirs(directory, exist_ok=True)
                except Exception as e:
                    print(f"Warning: Could not create directory {directory}: {e}")
    
    @classmethod
    def validate(cls):
        errors = []
        if not cls.SECRET_KEY or cls.SECRET_KEY == 'dev-secret-key-change-in-production':
            errors.append("SECRET_KEY must be set to a secure value in production")
        if not cls.ADMIN_ERROR_PASSWORD:
            errors.append("ADMIN_ERROR_PASSWORD must be set in .env")
        if cls.EMAIL_ENABLED:
            if not cls.SMTP_USER:
                errors.append("SMTP_USER is missing")
            if not cls.SMTP_PASSWORD:
                errors.append("SMTP_PASSWORD is missing")
            if not cls.SMTP_TO:
                errors.append("SMTP_TO is missing")
        return errors

Config.ensure_directories()

# ============================================
# CACHE CONFIGURATION
# ============================================

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
CACHE_LOCAL_MAX_SIZE = int(os.getenv('CACHE_LOCAL_MAX_SIZE', '1000'))
CACHE_LOCAL_TTL = int(os.getenv('CACHE_LOCAL_TTL', '60'))  # seconds
CACHE_SERIALIZATION = os.getenv('CACHE_SERIALIZATION', 'json')  # 'json', 'pickle', 'msgpack'
REDIS_MAX_CONNECTIONS = int(os.getenv('REDIS_MAX_CONNECTIONS', '10'))

# Cache TTLs per namespace (seconds)
CACHE_TTL = {
    'user': {
        'profile': 300,      # 5 minutes
        'preferences': 600,
    },
    'subject': {
        'list': 3600,        # 1 hour
        'data': 1800,
    },
    'quiz': {
        'state': 60,         # 1 minute (live quiz state)
        'participants': 30,
        'leaderboard': 10,
    },
    'leaderboard': {
        'global': 30,
        'subject': 30,
    },
    'pdf': {
        'list': 600,
        'metadata': 600,
    },
    'group': {
        'list': 600,
        'data': 600,
    },
    'notification': {
        'unread': 10,
        'list': 60,
    },
    'admin': {
        'stats': 300,
    },
    'session': {
        'data': 86400,       # 1 day (matches session timeout)
    },
}