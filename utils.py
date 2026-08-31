from datetime import datetime, timezone, timedelta
import re
from flask import request, session  # added for CSRF

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
# CSRF VALIDATION (moved from app.py to avoid circular import)
# ============================================

def validate_csrf():
    """Validate CSRF token from form or header; returns True if valid."""
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or token != session.get('csrf_token'):
        return False
    return True