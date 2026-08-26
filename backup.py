# ============================================
# DATABASE BACKUP SYSTEM
# ============================================
# Creates automated backups in the BACKUPS folder
# Saves in root directory with timestamp
# ============================================

import os
import shutil
import gzip
import sqlite3
import time
from datetime import datetime, timedelta
import glob

# ============================================
# CONFIGURATION
# ============================================

# Database location
DB_PATH = 'nuunplatform.db'

# Backup directory (in root)
BACKUP_DIR = 'BACKUPS'

# Subdirectories
DAILY_DIR = os.path.join(BACKUP_DIR, 'daily')
WEEKLY_DIR = os.path.join(BACKUP_DIR, 'weekly')
RESTORE_DIR = os.path.join(BACKUP_DIR, 'restore_points')

# Retention
MAX_DAILY = 7  # Keep 7 daily backups
MAX_WEEKLY = 4  # Keep 4 weekly backups
MAX_RESTORE = 3  # Keep 3 restore points

# ============================================
# INITIALIZATION
# ============================================

def init_backup_system():
    """Create backup directories if they don't exist"""
    for directory in [BACKUP_DIR, DAILY_DIR, WEEKLY_DIR, RESTORE_DIR]:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"Created backup directory: {directory}")

# ============================================
# BACKUP FUNCTIONS
# ============================================

def create_backup(backup_type='daily'):
    """
    Create a database backup
    
    Args:
        backup_type: 'daily', 'weekly', or 'restore'
    
    Returns:
        String: Path to the backup file, or None on failure
    """
    try:
        # Check if database exists
        if not os.path.exists(DB_PATH):
            print(f"Error: Database {DB_PATH} not found!")
            return None
        
        # Generate timestamp
        now = datetime.now()
        timestamp = now.strftime('%Y-%m-%d_%H-%M')
        
        # Determine backup directory
        if backup_type == 'daily':
            backup_dir = DAILY_DIR
            prefix = 'daily'
        elif backup_type == 'weekly':
            backup_dir = WEEKLY_DIR
            prefix = 'weekly'
        elif backup_type == 'restore':
            backup_dir = RESTORE_DIR
            prefix = 'restore'
        else:
            backup_dir = DAILY_DIR
            prefix = 'backup'
        
        # Create backup filename
        if backup_type == 'weekly':
            # Weekly: use week number
            week_num = now.isocalendar()[1]
            filename = f"{prefix}_week{week_num}_{now.year}.db.gz"
        else:
            filename = f"{prefix}_{timestamp}.db.gz"
        
        backup_path = os.path.join(backup_dir, filename)
        
        # Step 1: Copy database to temporary file (to avoid locking)
        temp_db = 'temp_backup.db'
        shutil.copy2(DB_PATH, temp_db)
        
        # Step 2: Verify the backup is valid
        try:
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            
            if result[0] != 'ok':
                print(f"Warning: Database integrity check failed! Backup may be corrupt.")
                # Still proceed, but log warning
        except Exception as e:
            print(f"Error verifying database: {e}")
            # Continue anyway
        
        # Step 3: Compress backup
        with open(temp_db, 'rb') as f_in:
            with gzip.open(backup_path, 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Step 4: Remove temporary file
        if os.path.exists(temp_db):
            os.remove(temp_db)
        
        # Step 5: Create symlink to latest backup
        latest_link = os.path.join(BACKUP_DIR, 'latest_backup.db.gz')
        if os.path.exists(latest_link) or os.path.islink(latest_link):
            os.unlink(latest_link)
        os.symlink(backup_path, latest_link)
        
        # Step 6: Log backup
        log_path = os.path.join(BACKUP_DIR, 'backup_log.txt')
        with open(log_path, 'a') as f:
            f.write(f"{timestamp}: {backup_type} backup created: {filename}\n")
            f.write(f"    Size: {os.path.getsize(backup_path) / 1024:.2f} KB\n")
            f.write(f"    Location: {backup_path}\n\n")
        
        # Step 7: Clean old backups
        clean_old_backups(backup_type)
        
        print(f"✅ {backup_type} backup created: {filename}")
        return backup_path
        
    except Exception as e:
        print(f"❌ Error creating backup: {e}")
        # Clean up temp file if it exists
        if os.path.exists('temp_backup.db'):
            os.remove('temp_backup.db')
        return None

# ============================================
# CLEANUP FUNCTIONS
# ============================================

def clean_old_backups(backup_type='daily'):
    """Remove old backups based on retention policy"""
    try:
        if backup_type == 'daily':
            backup_dir = DAILY_DIR
            max_keep = MAX_DAILY
        elif backup_type == 'weekly':
            backup_dir = WEEKLY_DIR
            max_keep = MAX_WEEKLY
        else:
            backup_dir = RESTORE_DIR
            max_keep = MAX_RESTORE
        
        # Get all backup files
        backup_files = glob.glob(os.path.join(backup_dir, '*.db.gz'))
        
        # Sort by modification time (oldest first)
        backup_files.sort(key=os.path.getmtime)
        
        # Remove old backups
        while len(backup_files) > max_keep:
            old_file = backup_files.pop(0)
            try:
                os.remove(old_file)
                print(f"Removed old backup: {os.path.basename(old_file)}")
            except Exception as e:
                print(f"Error removing old backup: {e}")
        
    except Exception as e:
        print(f"Error cleaning old backups: {e}")

# ============================================
# RESTORE FUNCTIONS
# ============================================

def restore_backup(backup_path=None):
    """
    Restore a database backup
    
    Args:
        backup_path: Path to backup file (if None, uses latest)
    
    Returns:
        Boolean: Success or failure
    """
    try:
        if not backup_path:
            # Use latest backup
            latest = os.path.join(BACKUP_DIR, 'latest_backup.db.gz')
            if not os.path.exists(latest):
                print(f"Error: No latest backup found!")
                return False
            backup_path = latest
        
        # Check if backup exists
        if not os.path.exists(backup_path):
            print(f"Error: Backup file {backup_path} not found!")
            return False
        
        # Create backup of current database first
        if os.path.exists(DB_PATH):
            pre_restore = os.path.join(RESTORE_DIR, f'pre_restore_{datetime.now().strftime("%Y-%m-%d_%H-%M")}.db')
            shutil.copy2(DB_PATH, pre_restore)
            print(f"Created pre-restore backup: {pre_restore}")
        
        # Decompress backup to temporary file
        temp_db = 'temp_restore.db'
        with gzip.open(backup_path, 'rb') as f_in:
            with open(temp_db, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Verify backup
        try:
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            
            if result[0] != 'ok':
                print(f"Warning: Backup integrity check failed!")
                response = input("Restore anyway? (y/n): ")
                if response.lower() != 'y':
                    if os.path.exists(temp_db):
                        os.remove(temp_db)
                    return False
        except Exception as e:
            print(f"Error verifying backup: {e}")
            if os.path.exists(temp_db):
                os.remove(temp_db)
            return False
        
        # Restore database
        shutil.copy2(temp_db, DB_PATH)
        
        # Clean up
        if os.path.exists(temp_db):
            os.remove(temp_db)
        
        print(f"✅ Database restored from: {backup_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error restoring backup: {e}")
        if os.path.exists('temp_restore.db'):
            os.remove('temp_restore.db')
        return False

# ============================================
# LIST BACKUPS
# ============================================

def list_backups():
    """List all available backups"""
    print("\n" + "=" * 60)
    print("   AVAILABLE BACKUPS")
    print("=" * 60)
    
    # Daily backups
    print("\n📅 Daily Backups:")
    daily = glob.glob(os.path.join(DAILY_DIR, '*.db.gz'))
    daily.sort(key=os.path.getmtime, reverse=True)
    for f in daily[:MAX_DAILY]:
        size = os.path.getsize(f) / 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M')
        print(f"   {os.path.basename(f)} ({size:.1f} KB) - {mtime}")
    
    # Weekly backups
    print("\n📊 Weekly Backups:")
    weekly = glob.glob(os.path.join(WEEKLY_DIR, '*.db.gz'))
    weekly.sort(key=os.path.getmtime, reverse=True)
    for f in weekly[:MAX_WEEKLY]:
        size = os.path.getsize(f) / 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M')
        print(f"   {os.path.basename(f)} ({size:.1f} KB) - {mtime}")
    
    # Restore points
    print("\n🔄 Restore Points:")
    restore = glob.glob(os.path.join(RESTORE_DIR, '*.db'))
    restore.sort(key=os.path.getmtime, reverse=True)
    for f in restore[:MAX_RESTORE]:
        size = os.path.getsize(f) / 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M')
        print(f"   {os.path.basename(f)} ({size:.1f} KB) - {mtime}")
    
    # Latest backup
    latest = os.path.join(BACKUP_DIR, 'latest_backup.db.gz')
    if os.path.exists(latest):
        size = os.path.getsize(latest) / 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(latest)).strftime('%Y-%m-%d %H:%M')
        print(f"\n⭐ Latest Backup: {os.path.basename(latest)} ({size:.1f} KB) - {mtime}")
    
    print("\n" + "=" * 60)

# ============================================
# MAIN EXECUTION
# ============================================

if __name__ == '__main__':
    import sys
    
    # Initialize backup system
    init_backup_system()
    
    # Parse arguments
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        
        if action == 'daily':
            create_backup('daily')
        elif action == 'weekly':
            create_backup('weekly')
        elif action == 'restore':
            # List backups first
            list_backups()
            print("\nEnter backup filename to restore (or leave blank for latest):")
            filename = input("> ").strip()
            if filename:
                # Search for file
                found = None
                for dir_path in [DAILY_DIR, WEEKLY_DIR, RESTORE_DIR]:
                    test_path = os.path.join(dir_path, filename)
                    if os.path.exists(test_path):
                        found = test_path
                        break
                if found:
                    restore_backup(found)
                else:
                    print(f"Backup file '{filename}' not found.")
            else:
                restore_backup()
        elif action == 'list':
            list_backups()
        elif action == 'clean':
            clean_old_backups('daily')
            clean_old_backups('weekly')
            clean_old_backups('restore')
        else:
            print("Usage: python backup.py [daily|weekly|restore|list|clean]")
    else:
        # Default: daily backup
        create_backup('daily')