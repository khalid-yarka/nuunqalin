from datetime import datetime, timezone, timedelta
import re
from flask import request, session
import secrets
import logging

logger = logging.getLogger(__name__)

# ============================================
# SOMALI TIME ZONE (UTC+3)
# ============================================

SOMALI_TIMEZONE = timezone(timedelta(hours=3))

def get_somali_time() -> datetime:
    """Get current time in Somali timezone (UTC+3)"""
    return datetime.now(SOMALI_TIMEZONE)

def format_somali_time(dt=None) -> str:
    """Format datetime in Somali format: 2026/9/24 4:32 PM
       Converts any timezone-aware datetime to Somali time."""
    if dt is None:
        dt = get_somali_time()
    else:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(SOMALI_TIMEZONE)

    year = dt.year
    month = dt.month
    day = dt.day
    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    minute = dt.minute
    am_pm = "AM" if dt.hour < 12 else "PM"
    
    return f"{year}/{month}/{day} {hour}:{minute:02d} {am_pm}"

def parse_somali_time(time_str: str) -> datetime:
    """Parse Somali time format: 2026/9/24 4:32 PM"""
    patterns = [
        r'(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})\s+(AM|PM)',
        r'(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})\s+(AM|PM)',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, time_str)
        if match:
            year, month, day, hour, minute, am_pm = match.groups()
            hour = int(hour)
            if am_pm == 'PM' and hour != 12:
                hour += 12
            elif am_pm == 'AM' and hour == 12:
                hour = 0
            
            dt = datetime(int(year), int(month), int(day), hour, int(minute))
            return dt.replace(tzinfo=SOMALI_TIMEZONE)
    
    raise ValueError(f"Could not parse time string: {time_str}")

def get_somali_time_db() -> str:
    """Get current time formatted for SQLite database storage (ISO with Somali time)"""
    dt = get_somali_time()
    return dt.isoformat()

def get_somali_time_display() -> str:
    """Get current time formatted for display: 2026/9/24 4:32 PM"""
    return format_somali_time()

def format_time_ago(timestamp: str) -> str:
    """Convert timestamp to 'X ago' format in Somali time"""
    if not timestamp:
        return 'Hadda'
    
    try:
        if 'T' in timestamp:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = parse_somali_time(timestamp)
        
        now = get_somali_time()
        diff = now - dt
        
        if diff.days > 30:
            months = diff.days // 30
            return f'{months} bilood ka hor' if months > 1 else 'bil ka hor'
        elif diff.days > 0:
            return f'{diff.days} maalin ka hor' if diff.days > 1 else 'maalin ka hor'
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f'{hours} saac ka hor' if hours > 1 else 'saac ka hor'
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f'{minutes} daqiiqo ka hor' if minutes > 1 else 'daqiiqo ka hor'
        else:
            return 'Hadda'
    except Exception:
        return 'Hadda'

# ============================================
# CSRF VALIDATION
# ============================================

def ensure_csrf_token():
    """
    Ensure a CSRF token exists in the session.
    Call this on GET requests that render forms.
    Does NOT mark session as modified if token already exists.
    """
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
        session.modified = True
        logger.debug("CSRF token generated and stored in session.")
    # Token already exists – leave session.modified unchanged
    return session['csrf_token']

def validate_csrf():
    """
    Validate CSRF token from form or header.
    Returns True if valid, False otherwise.
    """
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    expected = session.get('csrf_token')

    if not expected:
        logger.warning("CSRF validation failed: no token in session (session may be missing or expired).")
        return False

    if not token:
        logger.warning("CSRF validation failed: no token submitted in request.")
        return False

    # Use secrets.compare_digest for constant-time comparison
    if secrets.compare_digest(token, expected):
        return True
    else:
        logger.warning("CSRF validation failed: submitted token does not match session token.")
        return False
        
# utils.py – append this function at the end of the file

def time_ago(dt_str: str) -> str:
    """
    Convert an ISO timestamp to a human‑readable 'X ago' string.
    """
    if not dt_str:
        return "Just now"
    try:
        # Handle both 'Z' and '+00:00' timezone formats
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        now = get_somali_time()
        diff = now - dt

        seconds = diff.total_seconds()
        if seconds < 60:
            return "Just now"
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        hours = int(minutes // 60)
        if hours < 24:
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        days = int(hours // 24)
        if days < 7:
            return f"{days} day{'s' if days > 1 else ''} ago"
        weeks = int(days // 7)
        if weeks < 4:
            return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        months = int(days // 30)
        if months < 12:
            return f"{months} month{'s' if months > 1 else ''} ago"
        years = int(days // 365)
        return f"{years} year{'s' if years > 1 else ''} ago"
    except Exception:
        return dt_str        