import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Database
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'nuunplatform.db')
    DB_TIMEOUT = float(os.getenv('DB_TIMEOUT', '10.0'))
    DB_BUSY_TIMEOUT = int(os.getenv('DB_BUSY_TIMEOUT', '10000'))
    DB_RETRY_ATTEMPTS = int(os.getenv('DB_RETRY_ATTEMPTS', '3'))
    DB_RETRY_DELAY = float(os.getenv('DB_RETRY_DELAY', '0.1'))
    
    # Session configuration
    SESSION_TYPE = 'filesystem'
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)  # 24 hours
    
    # File upload settings (for PDFs)
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static/uploads/pdfs')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size
    
    # NEW: Backup configuration
    BACKUP_DIR = os.getenv('BACKUP_DIR', 'BACKUPS')
    BACKUP_ENABLED = os.getenv('BACKUP_ENABLED', 'true').lower() == 'true'
    BACKUP_TRIGGER_TOKEN = os.getenv('BACKUP_TRIGGER_TOKEN', 'change_this_token_in_production')
    
    # NEW: Quiz configuration
    RATING_TIME = int(os.getenv('RATING_TIME', '10'))
    LIVE_QUIZ_TIME_PER_QUESTION = int(os.getenv('LIVE_QUIZ_TIME_PER_QUESTION', '30'))
    LIVE_QUIZ_MAX_PARTICIPANTS = int(os.getenv('LIVE_QUIZ_MAX_PARTICIPANTS', '50'))
    
    # NEW: Rate limiting
    RATE_LIMIT_DEFAULT = os.getenv('RATE_LIMIT_DEFAULT', '200 per day;50 per hour')
    RATE_LIMIT_LOGIN = os.getenv('RATE_LIMIT_LOGIN', '5 per minute')