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