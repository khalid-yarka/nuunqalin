#!/usr/bin/env python3
# ============================================
# NUUNPLATFORM BACKUP RUNNER
# ============================================
# For use with PythonAnywhere Scheduled Tasks / Cron
# ============================================

import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

# ============================================
# SETUP PATHS
# ============================================

# Get base directory (where this script is located)
BASE_DIR = Path(__file__).resolve().parent

# Add base directory to path if needed
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Try to import config
try:
    from config import Config
    BACKUP_DIR = getattr(Config, 'BACKUP_DIR', str(BASE_DIR / 'BACKUPS'))
    LOG_DIR = getattr(Config, 'LOG_DIR', str(BASE_DIR / 'logs'))
except ImportError:
    BACKUP_DIR = str(BASE_DIR / 'BACKUPS')
    LOG_DIR = str(BASE_DIR / 'logs')

# Ensure directories exist
for directory in [BACKUP_DIR, LOG_DIR]:
    if not os.path.exists(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception:
            pass

# Log file
LOG_FILE = os.path.join(LOG_DIR, 'backup_runner.log')

# ============================================
# LOGGING
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================
# BACKUP FUNCTION
# ============================================

def run_backup(backup_type='daily'):
    """Run a backup and log the result."""
    start_time = time.time()
    logger.info(f"Starting {backup_type} backup...")
    
    try:
        from backup import BackupManager, acquire_backup_lock, release_backup_lock, is_backup_locked
        
        manager = BackupManager()
        
        # Check if backup is already running
        if is_backup_locked():
            logger.warning("Backup already running, skipping")
            return False
        
        # Acquire lock
        lock_fd = acquire_backup_lock()
        if lock_fd is None:
            logger.error("Could not acquire backup lock")
            return False
        
        try:
            # Run backup
            result = manager.create_backup(backup_type)
            duration = time.time() - start_time
            
            if result['success']:
                logger.info(
                    f"✅ Backup successful: {result['filename']} "
                    f"({result['size_bytes'] / 1024:.2f} KB) "
                    f"in {duration:.2f}s"
                )
                
                # Also run maintenance to clean old backups
                maintenance_result = manager.run_maintenance(dry_run=False)
                if maintenance_result['deleted']:
                    logger.info(f"Cleaned {len(maintenance_result['deleted'])} old backups")
                
                return True
            else:
                logger.error(f"❌ Backup failed: {result['message']}")
                return False
                
        finally:
            release_backup_lock(lock_fd)
            
    except ImportError as e:
        logger.error(f"Backup module import error: {e}")
        return False
    except Exception as e:
        logger.error(f"Backup error: {e}", exc_info=True)
        return False


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='NUUNPLATFORM Backup Runner')
    parser.add_argument('--type', default='daily', 
                       choices=['daily', 'weekly', 'monthly', 'manual'],
                       help='Type of backup to run')
    parser.add_argument('--check', action='store_true',
                       help='Check backup health and exit')
    
    args = parser.parse_args()
    
    if args.check:
        # Health check only
        try:
            from backup import BackupManager
            manager = BackupManager()
            health = manager.health_check()
            
            print(f"Backup System Health: {health['status']}")
            print(f"  Valid backups: {health['valid_count']}")
            print(f"  Total backups: {health['backup_count']}")
            print(f"  DB integrity: {'OK' if health['db_integrity'] else 'FAILED'}")
            print(f"  WAL mode: {'Enabled' if health.get('wal_enabled') else 'Disabled'}")
            
            if health['issues']:
                print("  Issues:")
                for issue in health['issues']:
                    print(f"    - {issue}")
            
            # Return exit code based on health
            if health['status'] == 'critical':
                sys.exit(2)
            elif health['status'] == 'warning':
                sys.exit(1)
            else:
                sys.exit(0)
                
        except Exception as e:
            print(f"Health check failed: {e}")
            sys.exit(2)
    else:
        # Run backup
        success = run_backup(args.type)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()