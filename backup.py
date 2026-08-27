#!/usr/bin/env python3
# ============================================
# NUUNPLATFORM BACKUP SYSTEM
# ============================================
# Advanced backup management with verification,
# checksums, manifest, safe restore, and CLI.
# ============================================

import os
import sys
import sqlite3
import json
import gzip
import shutil
import hashlib
import time
import argparse
import logging
import fcntl
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ============================================
# CONFIGURATION
# ============================================

DEFAULT_DB_PATH = 'nuunplatform.db'
DEFAULT_BACKUP_DIR = 'BACKUPS'
DEFAULT_LOG_FILE = 'backup.log'
BACKUP_LOCK_FILE = os.path.join(DEFAULT_BACKUP_DIR, 'backup.lock')

# Try to load from config.py
try:
    from config import Config
    DEFAULT_DB_PATH = getattr(Config, 'DATABASE_PATH', 'nuunplatform.db')
    DEFAULT_BACKUP_DIR = getattr(Config, 'BACKUP_DIR', 'BACKUPS')
except ImportError:
    pass

RETENTION = {
    'daily': 7,
    'weekly': 4,
    'monthly': 12,
    'manual': None,
}

BACKUP_TYPES = {
    'daily': {'label': 'Daily', 'retention': 7},
    'weekly': {'label': 'Weekly', 'retention': 4},
    'monthly': {'label': 'Monthly', 'retention': 12},
    'manual': {'label': 'Manual', 'retention': None},
}

# ANSI color codes
COLOR_GREEN = '\033[92m'
COLOR_RED = '\033[91m'
COLOR_YELLOW = '\033[93m'
COLOR_BLUE = '\033[94m'
COLOR_CYAN = '\033[96m'
COLOR_RESET = '\033[0m'
COLOR_BOLD = '\033[1m'

# ============================================
# BACKUP LOCKING
# ============================================

def acquire_backup_lock(lock_file=BACKUP_LOCK_FILE, timeout=30):
    """
    Acquire exclusive lock for backup.
    Returns file descriptor if acquired, None if already locked.
    """
    try:
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)

        fd = open(lock_file, 'w')
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fd.write(str(os.getpid()))
                fd.flush()
                return fd
            except (IOError, OSError):
                time.sleep(1)

        return None
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to acquire backup lock: {e}")
        return None

def release_backup_lock(fd):
    """Release backup lock."""
    if fd:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            fd.close()
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to release backup lock: {e}")

def is_backup_locked(lock_file=BACKUP_LOCK_FILE):
    """Check if backup is currently locked."""
    try:
        fd = open(lock_file, 'r')
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            return False
        except (IOError, OSError):
            return True
        finally:
            fd.close()
    except FileNotFoundError:
        return False
    except Exception:
        return False

# ============================================
# LOGGING SETUP
# ============================================

def setup_logging(verbose=False, log_file=None):
    """Configure logging for backup operations."""
    handlers = []

    log_path = log_file or DEFAULT_LOG_FILE
    try:
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            '%Y-%m-%d %H:%M:%S'
        ))
        handlers.append(file_handler)
    except Exception as e:
        print(f"Warning: Could not create log file: {e}")

    if verbose or not handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            '%Y-%m-%d %H:%M:%S'
        ))
        handlers.append(stream_handler)

    if not handlers:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)

    logging.basicConfig(
        level=logging.INFO if not verbose else logging.DEBUG,
        handlers=handlers
    )
    return logging.getLogger(__name__)

# ============================================
# BACKUP MANAGER CLASS
# ============================================

class BackupManager:
    """Main backup management system with verification and atomic operations."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH, backup_dir: str = DEFAULT_BACKUP_DIR):
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.manifest_path = os.path.join(backup_dir, 'manifest.json')
        self.last_good_link = os.path.join(backup_dir, 'LAST_KNOWN_GOOD')
        self.temp_dir = os.path.join(backup_dir, 'temp')

        os.makedirs(backup_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        self.manifest = self._load_manifest()
        self.logger = logging.getLogger(__name__)

    # ============================================
    # MANIFEST MANAGEMENT
    # ============================================

    def _load_manifest(self) -> Dict:
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                self.logger.warning("Manifest corrupted, creating new.")
                return self._create_empty_manifest()
        return self._create_empty_manifest()

    def _create_empty_manifest(self) -> Dict:
        return {
            'backups': [],
            'last_good': None,
            'last_created': None,
            'total_backups': 0,
            'valid_backups': 0,
            'version': '1.0'
        }

    def _save_manifest(self):
        temp_path = os.path.join(self.temp_dir, 'manifest_temp.json')
        with open(temp_path, 'w') as f:
            json.dump(self.manifest, f, indent=2)
        shutil.move(temp_path, self.manifest_path)

    # ============================================
    # CHECKSUM & VERIFICATION
    # ============================================

    @staticmethod
    def calculate_checksum(file_path: str) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def verify_database_integrity(db_path: str) -> Tuple[bool, str]:
        try:
            conn = sqlite3.connect(db_path, timeout=10)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            if result and result[0] == 'ok':
                return True, "ok"
            return False, result[0] if result else "unknown error"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def verify_tables_exist(db_path: str, required_tables=None) -> bool:
        if required_tables is None:
            required_tables = ['students', 'questions', 'subjects', 'quiz_attempts']
        try:
            conn = sqlite3.connect(db_path, timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            conn.close()
            for table in required_tables:
                if table not in tables:
                    return False
            return True
        except Exception:
            return False

    def verify_backup(self, backup_path: str, skip_checksum: bool = False) -> Tuple[bool, Dict]:
        details = {
            'integrity': False,
            'tables': False,
            'checksum_match': False,
            'size_bytes': 0,
            'error': None
        }

        if not os.path.exists(backup_path):
            details['error'] = "File not found"
            return False, details

        details['size_bytes'] = os.path.getsize(backup_path)

        temp_db = os.path.join(self.temp_dir, f"verify_{int(time.time())}.db")
        try:
            with gzip.open(backup_path, 'rb') as f_in:
                with open(temp_db, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            integrity_ok, msg = self.verify_database_integrity(temp_db)
            details['integrity'] = integrity_ok
            details['integrity_msg'] = msg

            if not integrity_ok:
                details['error'] = f"Integrity check failed: {msg}"
                os.remove(temp_db)
                return False, details

            tables_ok = self.verify_tables_exist(temp_db)
            details['tables'] = tables_ok
            if not tables_ok:
                details['error'] = "Required tables missing"
                os.remove(temp_db)
                return False, details

            if not skip_checksum:
                entry = self._find_backup_entry(backup_path)
                if entry and 'checksum' in entry:
                    current_checksum = self.calculate_checksum(backup_path)
                    if current_checksum == entry['checksum']:
                        details['checksum_match'] = True
                    else:
                        details['checksum_match'] = False
                        details['error'] = "Checksum mismatch"
                        os.remove(temp_db)
                        return False, details

            os.remove(temp_db)
            return True, details

        except Exception as e:
            details['error'] = str(e)
            if os.path.exists(temp_db):
                os.remove(temp_db)
            return False, details

    def _find_backup_entry(self, backup_path: str) -> Optional[Dict]:
        filename = os.path.basename(backup_path)
        for entry in self.manifest['backups']:
            if entry['filename'] == filename:
                return entry
        return None

    # ============================================
    # BACKUP CREATION
    # ============================================

    def create_backup(self, backup_type: str = 'daily') -> Dict:
        start_time = time.time()
        result = {
            'success': False,
            'filename': None,
            'message': '',
            'verified': False,
            'size_bytes': 0,
            'checksum': None,
            'duration': 0
        }

        try:
            if backup_type not in BACKUP_TYPES:
                result['message'] = f"Invalid backup type: {backup_type}"
                return result

            if not os.path.exists(self.db_path):
                result['message'] = f"Database not found: {self.db_path}"
                return result

            if not self._check_disk_space():
                result['message'] = "Insufficient disk space"
                return result

            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
            if backup_type == 'manual':
                filename = f"manual_{timestamp}.db.gz"
            else:
                filename = f"{backup_type}_{timestamp}.db.gz"
            full_path = os.path.join(self.backup_dir, filename)
            temp_backup = os.path.join(self.temp_dir, f"backup_TEMP_{timestamp}.db")
            temp_gz = os.path.join(self.temp_dir, f"backup_TEMP_{timestamp}.db.gz")

            self.logger.info(f"Creating {backup_type} backup...")
            source_conn = sqlite3.connect(self.db_path, timeout=10)
            dest_conn = sqlite3.connect(temp_backup, timeout=10)
            source_conn.execute("PRAGMA journal_mode = WAL")
            source_conn.backup(dest_conn)
            dest_conn.commit()
            source_conn.close()
            dest_conn.close()

            self.logger.info("Compressing backup...")
            with open(temp_backup, 'rb') as f_in:
                with gzip.open(temp_gz, 'wb', compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)

            self.logger.info("Verifying compressed backup...")
            ver_ok, ver_details = self.verify_backup(temp_gz, skip_checksum=True)
            if not ver_ok:
                result['message'] = f"Verification failed: {ver_details.get('error')}"
                os.remove(temp_gz)
                os.remove(temp_backup)
                return result

            checksum = self.calculate_checksum(temp_gz)
            shutil.move(temp_gz, full_path)
            os.remove(temp_backup)

            entry = {
                'filename': filename,
                'type': backup_type,
                'timestamp': datetime.now().isoformat(),
                'size_bytes': os.path.getsize(full_path),
                'checksum': checksum,
                'integrity_status': 'valid',
                'integrity_result': 'ok',
                'tables_verified': True,
                'verification_timestamp': datetime.now().isoformat(),
                'creation_duration_seconds': round(time.time() - start_time, 2),
                'notes': ''
            }
            self.manifest['backups'].append(entry)
            self.manifest['total_backups'] += 1
            self.manifest['valid_backups'] += 1
            self.manifest['last_created'] = entry['timestamp']
            self.manifest['last_good'] = filename

            self._update_last_good_link(full_path)
            self._save_manifest()

            result['success'] = True
            result['filename'] = filename
            result['message'] = f"{backup_type.capitalize()} backup created successfully"
            result['verified'] = True
            result['size_bytes'] = entry['size_bytes']
            result['checksum'] = checksum
            result['duration'] = entry['creation_duration_seconds']

            self.logger.info(f"Backup created: {filename} ({result['duration']}s)")
            return result

        except Exception as e:
            self.logger.error(f"Backup creation failed: {e}", exc_info=True)
            result['message'] = str(e)
            for f in [temp_backup, temp_gz]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass
            return result

    def _check_disk_space(self) -> bool:
        try:
            stat = os.statvfs(self.backup_dir)
            free_bytes = stat.f_frsize * stat.f_bavail
            free_mb = free_bytes / (1024 * 1024)
            if free_mb < 50:
                self.logger.warning(f"Low disk space: {free_mb:.2f} MB free")
                return False
            return True
        except Exception:
            return True

    def _update_last_good_link(self, backup_path: str):
        try:
            if os.path.exists(self.last_good_link) or os.path.islink(self.last_good_link):
                os.unlink(self.last_good_link)
            rel_path = os.path.relpath(backup_path, os.path.dirname(self.last_good_link))
            os.symlink(rel_path, self.last_good_link)
        except Exception as e:
            self.logger.warning(f"Could not update LAST_KNOWN_GOOD link: {e}")

    # ============================================
    # RESTORE OPERATIONS
    # ============================================

    def restore_latest(self, force: bool = False) -> Dict:
        latest = self.get_latest_valid_backup()
        if not latest:
            return {'success': False, 'message': 'No valid backup found'}
        return self.restore_backup(latest, force=force)

    def restore_backup(self, filename: str, force: bool = False) -> Dict:
        result = {
            'success': False,
            'message': '',
            'backup_verified': False,
            'safety_copy_created': False,
            'temp_restore_verified': False
        }

        if os.environ.get('BACKUP_NON_INTERACTIVE') and not force:
            result['message'] = "Non-interactive mode: use --force to restore"
            return result

        backup_path = os.path.join(self.backup_dir, filename)
        if not os.path.exists(backup_path):
            result['message'] = f"Backup file not found: {filename}"
            return result

        self.logger.info(f"Verifying backup: {filename}")
        ver_ok, ver_details = self.verify_backup(backup_path)
        if not ver_ok:
            result['message'] = f"Backup verification failed: {ver_details.get('error')}"
            return result
        result['backup_verified'] = True

        if os.path.exists(self.db_path):
            safety_path = os.path.join(
                self.temp_dir,
                f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            )
            try:
                shutil.copy2(self.db_path, safety_path)
                result['safety_copy_created'] = True
                self.logger.info(f"Safety copy created: {safety_path}")
            except Exception as e:
                result['message'] = f"Failed to create safety copy: {e}"
                return result

        temp_restore = os.path.join(self.temp_dir, f"temp_restore_{int(time.time())}.db")
        try:
            with gzip.open(backup_path, 'rb') as f_in:
                with open(temp_restore, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            ver_ok2, ver_details2 = self.verify_database_integrity(temp_restore)
            if not ver_ok2:
                result['message'] = f"Restored database integrity check failed: {ver_details2}"
                os.remove(temp_restore)
                return result

            tables_ok = self.verify_tables_exist(temp_restore)
            if not tables_ok:
                result['message'] = "Restored database missing required tables"
                os.remove(temp_restore)
                return result

            result['temp_restore_verified'] = True

            wal_path = self.db_path + '-wal'
            shm_path = self.db_path + '-shm'
            for p in [wal_path, shm_path]:
                if os.path.exists(p):
                    os.remove(p)

            shutil.move(temp_restore, self.db_path)

            live_ok, live_msg = self.verify_database_integrity(self.db_path)
            if not live_ok:
                self.logger.error(f"Live DB verification failed after restore: {live_msg}")
                if result['safety_copy_created']:
                    shutil.move(safety_path, self.db_path)
                    result['message'] = "Restore failed, reverted to safety copy"
                    return result
                else:
                    result['message'] = "Restore failed and no safety copy available"
                    return result

            result['success'] = True
            result['message'] = f"Database restored successfully from {filename}"
            self.manifest['last_good'] = filename
            self._update_last_good_link(backup_path)
            self._save_manifest()

            self.logger.info(f"Restore successful from {filename}")
            return result

        except Exception as e:
            self.logger.error(f"Restore failed: {e}", exc_info=True)
            result['message'] = str(e)
            if os.path.exists(temp_restore):
                os.remove(temp_restore)
            return result

    # ============================================
    # BACKUP QUERIES & HEALTH
    # ============================================

    def get_latest_valid_backup(self) -> Optional[str]:
        valid = [b for b in self.manifest['backups'] if b.get('integrity_status') == 'valid']
        if not valid:
            return None
        valid.sort(key=lambda x: x['timestamp'], reverse=True)
        return valid[0]['filename']

    def get_backup_list(self, valid_only=False) -> List[Dict]:
        backups = self.manifest['backups']
        if valid_only:
            backups = [b for b in backups if b.get('integrity_status') == 'valid']
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        return backups

    def health_check(self) -> Dict:
        result = {
            'status': 'healthy',
            'issues': [],
            'backup_count': len(self.manifest['backups']),
            'valid_count': 0,
            'invalid_count': 0,
            'last_good': self.manifest.get('last_good'),
            'last_created': self.manifest.get('last_created'),
            'db_integrity': False,
            'disk_free_mb': 0,
            'backup_dir_writable': True,
        }

        if os.path.exists(self.db_path):
            db_ok, msg = self.verify_database_integrity(self.db_path)
            result['db_integrity'] = db_ok
            if not db_ok:
                result['issues'].append(f"Live database integrity check failed: {msg}")

        for entry in self.manifest['backups']:
            if entry.get('integrity_status') == 'valid':
                result['valid_count'] += 1
            else:
                result['invalid_count'] += 1

        try:
            stat = os.statvfs(self.backup_dir)
            free_bytes = stat.f_frsize * stat.f_bavail
            result['disk_free_mb'] = free_bytes / (1024 * 1024)
            if result['disk_free_mb'] < 50:
                result['issues'].append(f"Low disk space: {result['disk_free_mb']:.2f} MB")
        except:
            pass

        try:
            test_file = os.path.join(self.backup_dir, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
        except:
            result['backup_dir_writable'] = False
            result['issues'].append("Backup directory is not writable")

        if self.manifest.get('last_good'):
            last_good_path = os.path.join(self.backup_dir, self.manifest['last_good'])
            if not os.path.exists(last_good_path):
                result['issues'].append("LAST_KNOWN_GOOD backup file missing")
        else:
            result['issues'].append("No last known good backup set")

        if self.manifest.get('last_created'):
            try:
                last_created = datetime.fromisoformat(self.manifest['last_created'])
                age = datetime.now() - last_created
                if age > timedelta(days=7):
                    result['issues'].append(f"Last backup is {age.days} days old")
            except:
                pass

        if result['issues']:
            result['status'] = 'warning'
        if result['valid_count'] == 0 or not result['db_integrity']:
            result['status'] = 'critical'

        return result

    # ============================================
    # MAINTENANCE & ROTATION
    # ============================================

    def run_maintenance(self, dry_run=False) -> Dict:
        result = {
            'deleted': [],
            'kept': [],
            'errors': [],
            'dry_run': dry_run
        }

        by_type = {}
        for entry in self.manifest['backups']:
            btype = entry.get('type', 'manual')
            by_type.setdefault(btype, []).append(entry)

        last_good = self.manifest.get('last_good')

        for btype, entries in by_type.items():
            entries.sort(key=lambda x: x['timestamp'], reverse=True)
            retention = RETENTION.get(btype)
            if retention is None:
                continue

            to_keep = entries[:retention]
            to_delete = entries[retention:]

            for entry in to_keep:
                result['kept'].append(entry['filename'])

            for entry in to_delete:
                if entry['filename'] == last_good:
                    result['kept'].append(entry['filename'])
                    continue

                file_path = os.path.join(self.backup_dir, entry['filename'])
                if not dry_run:
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            result['deleted'].append(entry['filename'])
                            self.manifest['backups'].remove(entry)
                    except Exception as e:
                        result['errors'].append(f"Failed to delete {entry['filename']}: {e}")
                else:
                    result['deleted'].append(entry['filename'])

        if not dry_run:
            self._save_manifest()

        return result

    # ============================================
    # VERIFICATION COMMANDS
    # ============================================

    def verify_all_backups(self) -> Dict:
        results = {
            'total': 0,
            'valid': 0,
            'invalid': 0,
            'errors': [],
            'details': []
        }

        for entry in self.manifest['backups']:
            results['total'] += 1
            file_path = os.path.join(self.backup_dir, entry['filename'])
            if not os.path.exists(file_path):
                entry['integrity_status'] = 'missing'
                results['invalid'] += 1
                results['errors'].append(f"Missing file: {entry['filename']}")
                continue

            ver_ok, ver_details = self.verify_backup(file_path)
            if ver_ok:
                entry['integrity_status'] = 'valid'
                entry['integrity_result'] = 'ok'
                results['valid'] += 1
            else:
                entry['integrity_status'] = 'invalid'
                entry['integrity_result'] = ver_details.get('error', 'unknown')
                results['invalid'] += 1
                results['errors'].append(f"Invalid: {entry['filename']} - {ver_details.get('error')}")

            results['details'].append({
                'filename': entry['filename'],
                'status': entry['integrity_status'],
                'checksum': entry.get('checksum', 'N/A')
            })

        self._save_manifest()
        return results

    # ============================================
    # UTILITIES
    # ============================================

    def get_backup_info(self, filename: str) -> Optional[Dict]:
        for entry in self.manifest['backups']:
            if entry['filename'] == filename:
                return entry
        return None

    def get_latest_good_path(self) -> Optional[str]:
        if self.manifest.get('last_good'):
            path = os.path.join(self.backup_dir, self.manifest['last_good'])
            if os.path.exists(path):
                return path
        return None


# ============================================
# COLOR HELPERS
# ============================================

def green(text):
    return COLOR_GREEN + text + COLOR_RESET

def red(text):
    return COLOR_RED + text + COLOR_RESET

def yellow(text):
    return COLOR_YELLOW + text + COLOR_RESET

def cyan(text):
    return COLOR_CYAN + text + COLOR_RESET

def bold(text):
    return COLOR_BOLD + text + COLOR_RESET


# ============================================
# CLI INTERFACE
# ============================================

def create_parser():
    parser = argparse.ArgumentParser(
        description='NuunPlatform Backup Management System',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--non-interactive', action='store_true',
                        help='Run without prompts (for scheduled tasks)')
    parser.add_argument('--log-file', default=None,
                        help='Log file path (default: backup.log)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    list_parser = subparsers.add_parser('list', help='List backups')
    list_parser.add_argument('--valid', action='store_true', help='Show only valid backups')
    list_parser.add_argument('--json', action='store_true', help='Output as JSON')

    create_parser = subparsers.add_parser('create', help='Create a new backup')
    create_parser.add_argument('--type', default='daily',
                               choices=['daily', 'weekly', 'monthly', 'manual'],
                               help='Backup type (default: daily)')

    verify_parser = subparsers.add_parser('verify', help='Verify a specific backup')
    verify_parser.add_argument('filename', help='Backup filename to verify')

    subparsers.add_parser('verify-all', help='Verify all backups')
    subparsers.add_parser('health', help='Run health check')
    subparsers.add_parser('restore-latest', help='Restore the latest valid backup')

    restore_parser = subparsers.add_parser('restore', help='Restore a specific backup')
    restore_parser.add_argument('filename', help='Backup filename to restore')
    restore_parser.add_argument('--force', action='store_true', help='Force restore in non-interactive mode')

    maintenance_parser = subparsers.add_parser('maintenance', help='Remove expired backups')
    maintenance_parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted')

    subparsers.add_parser('info', help='Show backup system summary')
    subparsers.add_parser('dashboard', help='Show interactive dashboard')

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    if args.non_interactive:
        os.environ['BACKUP_NON_INTERACTIVE'] = '1'

    log_file = args.log_file or DEFAULT_LOG_FILE
    logger = setup_logging(verbose=args.verbose, log_file=log_file)

    if args.non_interactive and is_backup_locked():
        logger.info("Backup already running, skipping")
        sys.exit(0)

    manager = BackupManager()

    if not args.command or args.command == 'dashboard':
        if args.non_interactive:
            health = manager.health_check()
            if health['status'] == 'healthy':
                print(f"Backup system healthy. Valid backups: {health['valid_count']}")
                sys.exit(0)
            else:
                print(f"Backup system issues: {health['status']}")
                for issue in health['issues']:
                    print(f"  - {issue}")
                sys.exit(1)
        else:
            show_dashboard(manager)
        return

    # Execute commands
    if args.command == 'list':
        backups = manager.get_backup_list(valid_only=args.valid)
        if args.json:
            print(json.dumps(backups, indent=2))
        else:
            print_backup_list(backups, manager)
    elif args.command == 'create':
        result = manager.create_backup(args.type)
        if result['success']:
            print(green(f"✅ {result['message']}"))
            print(f"   Filename: {result['filename']}")
            print(f"   Size: {result['size_bytes'] / 1024:.2f} KB")
            print(f"   Checksum: {result['checksum'][:16]}...")
            print(f"   Duration: {result['duration']} seconds")
            sys.exit(0)
        else:
            print(red(f"❌ {result['message']}"))
            sys.exit(1)
    elif args.command == 'verify':
        ver_ok, details = manager.verify_backup(
            os.path.join(manager.backup_dir, args.filename)
        )
        if ver_ok:
            print(green(f"✅ Backup '{args.filename}' is VALID"))
            print(f"   Size: {details['size_bytes'] / 1024:.2f} KB")
            print(f"   Integrity: {details['integrity_msg']}")
            if 'checksum_match' in details:
                print(f"   Checksum: {'OK' if details['checksum_match'] else 'MISMATCH'}")
            sys.exit(0)
        else:
            print(red(f"❌ Backup '{args.filename}' is INVALID"))
            print(f"   Error: {details.get('error')}")
            sys.exit(1)
    elif args.command == 'verify-all':
        results = manager.verify_all_backups()
        print(f"Total backups: {results['total']}")
        print(green(f"✅ Valid: {results['valid']}"))
        print(red(f"❌ Invalid: {results['invalid']}"))
        if results['errors']:
            print("Errors:")
            for err in results['errors']:
                print(f"  - {err}")
        if results['invalid'] > 0:
            sys.exit(1)
    elif args.command == 'health':
        health = manager.health_check()
        print_health_report(health, manager)
        if health['status'] == 'critical':
            sys.exit(1)
    elif args.command == 'restore-latest':
        result = manager.restore_latest(force=args.force if hasattr(args, 'force') else False)
        if result['success']:
            print(green(f"✅ {result['message']}"))
            print(f"   Backup verified: {result['backup_verified']}")
            print(f"   Safety copy created: {result['safety_copy_created']}")
            print(f"   Temp restore verified: {result['temp_restore_verified']}")
            sys.exit(0)
        else:
            print(red(f"❌ Restore failed: {result['message']}"))
            sys.exit(1)
    elif args.command == 'restore':
        result = manager.restore_backup(args.filename, force=args.force if hasattr(args, 'force') else False)
        if result['success']:
            print(green(f"✅ {result['message']}"))
            print(f"   Backup verified: {result['backup_verified']}")
            print(f"   Safety copy created: {result['safety_copy_created']}")
            print(f"   Temp restore verified: {result['temp_restore_verified']}")
            sys.exit(0)
        else:
            print(red(f"❌ Restore failed: {result['message']}"))
            sys.exit(1)
    elif args.command == 'maintenance':
        result = manager.run_maintenance(dry_run=args.dry_run)
        if args.dry_run:
            print("DRY RUN - Would delete the following backups:")
        else:
            print("Deleted backups:")
        for f in result['deleted']:
            print(f"  - {f}")
        if result['errors']:
            print("Errors:")
            for err in result['errors']:
                print(f"  - {err}")
    elif args.command == 'info':
        print_info(manager)


def print_backup_list(backups, manager):
    if not backups:
        print("No backups found.")
        return
    print(f"\n{'Filename':<40} {'Type':<10} {'Size (KB)':<12} {'Status':<10} {'Date'}")
    print("-" * 80)
    for entry in backups:
        filename = entry['filename']
        btype = entry.get('type', 'manual')
        size_kb = entry.get('size_bytes', 0) / 1024
        status = entry.get('integrity_status', 'unknown')
        timestamp = entry.get('timestamp', '')[:16]
        is_last = filename == manager.manifest.get('last_good')
        status_str = status
        if is_last:
            status_str += " ⭐"
        print(f"{filename:<40} {btype:<10} {size_kb:<12.1f} {status_str:<10} {timestamp}")
    print()


def print_health_report(health, manager):
    print("\n" + "=" * 60)
    print("    BACKUP SYSTEM HEALTH REPORT")
    print("=" * 60)

    status_color = green if health['status'] == 'healthy' else (yellow if health['status'] == 'warning' else red)
    print(f"Status: {status_color(health['status'].upper())}")
    print(f"Total backups: {health['backup_count']}")
    print(f"Valid backups: {health['valid_count']}")
    print(f"Invalid backups: {health['invalid_count']}")
    print(f"Last good: {health['last_good'] or 'None'}")
    print(f"Last created: {health['last_created'] or 'Never'}")
    db_status = green("OK") if health['db_integrity'] else red("FAILED")
    print(f"DB integrity: {db_status}")
    print(f"Disk free: {health['disk_free_mb']:.2f} MB")
    print(f"Backup dir writable: {'Yes' if health['backup_dir_writable'] else 'No'}")
    if health['issues']:
        print("\nIssues:")
        for issue in health['issues']:
            print(f"  ⚠️ {issue}")
    print("=" * 60)


def print_info(manager):
    print("\nBackup System Information")
    print("-" * 40)
    print(f"Database: {manager.db_path}")
    print(f"Backup directory: {manager.backup_dir}")
    print(f"Manifest: {manager.manifest_path}")
    print(f"Total backups: {len(manager.manifest['backups'])}")
    print(f"Last good: {manager.manifest.get('last_good')}")
    print(f"Last created: {manager.manifest.get('last_created')}")
    print("\nRetention policies:")
    for btype, retention in RETENTION.items():
        if retention:
            print(f"  {btype}: {retention} copies")
        else:
            print(f"  {btype}: unlimited")


def show_dashboard(manager):
    """Show a colorful dashboard with backup status."""
    import os
    os.system('cls' if os.name == 'nt' else 'clear')
    print(COLOR_CYAN + "=" * 60 + COLOR_RESET)
    print(COLOR_YELLOW + "   🗄️  NUUNPLATFORM BACKUP DASHBOARD  " + COLOR_RESET)
    print(COLOR_CYAN + "=" * 60 + COLOR_RESET)

    health = manager.health_check()
    status_color = green if health['status'] == 'healthy' else (yellow if health['status'] == 'warning' else red)

    print(f"\nStatus: {status_color(health['status'].upper())}")
    print(f"Total backups: {health['backup_count']}")
    print(f"Valid: {health['valid_count']}  Invalid: {health['invalid_count']}")

    if health['last_good']:
        print(f"Last good: {green(health['last_good'])}")
    else:
        print(f"Last good: {red('None')}")

    print(f"Last created: {health['last_created'] or 'Never'}")
    db_status = green("OK") if health['db_integrity'] else red("FAILED")
    print(f"DB integrity: {db_status}")
    print(f"Disk free: {health['disk_free_mb']:.2f} MB")

    print("\n" + COLOR_BOLD + "Recent Backups:" + COLOR_RESET)
    backups = manager.get_backup_list(valid_only=False)[:5]
    if backups:
        print(f"{'Filename':<40} {'Status':<10} {'Date'}")
        print("-" * 70)
        for entry in backups:
            filename = entry['filename']
            status = entry.get('integrity_status', 'unknown')
            if status == 'valid':
                status_display = green("VALID")
            elif status == 'invalid':
                status_display = red("INVALID")
            else:
                status_display = status
            date = entry.get('timestamp', '')[:16]
            is_last = filename == health['last_good']
            marker = ' ⭐' if is_last else ''
            print(f"{filename:<40} {status_display:<10} {date}{marker}")
    else:
        print("  No backups available")

    if health['issues']:
        print("\n" + COLOR_YELLOW + "Issues:" + COLOR_RESET)
        for issue in health['issues']:
            print(f"  ⚠️ {issue}")

    print("\n" + COLOR_BOLD + "Available Commands:" + COLOR_RESET)
    print("  python backup.py create [--type daily|weekly|monthly|manual]")
    print("  python backup.py list [--valid]")
    print("  python backup.py verify <filename>")
    print("  python backup.py verify-all")
    print("  python backup.py health")
    print("  python backup.py restore-latest")
    print("  python backup.py restore <filename>")
    print("  python backup.py maintenance [--dry-run]")
    print("  python backup.py info")
    print("  python backup.py dashboard")
    print(COLOR_CYAN + "=" * 60 + COLOR_RESET)


if __name__ == '__main__':
    main()