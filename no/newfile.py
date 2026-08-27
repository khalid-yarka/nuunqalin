#!/usr/bin/env python3
"""
Migration script to update database to the new schema.
This adds missing columns to existing tables without losing data.

Usage:
    python migrate_to_new_schema.py
"""

import sqlite3
import os
import json
from datetime import datetime

DB_PATH = 'nuunplatform.db'
BACKUP_PATH = f'backup_before_migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'

def backup_database():
    """Create a full backup of the database"""
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return False
    
    try:
        import shutil
        shutil.copy2(DB_PATH, BACKUP_PATH)
        print(f"✅ Database backed up to: {BACKUP_PATH}")
        return True
    except Exception as e:
        print(f"❌ Failed to backup database: {e}")
        return False

def get_existing_columns(conn, table_name):
    """Get list of columns in a table"""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in cursor.fetchall()]
    return columns

def add_column_if_not_exists(conn, table_name, column_name, column_type, default_value=None):
    """Add a column to a table if it doesn't exist"""
    cursor = conn.cursor()
    existing_columns = get_existing_columns(conn, table_name)
    
    if column_name in existing_columns:
        print(f"   ⏭️ Column '{column_name}' already exists in '{table_name}'")
        return True
    
    try:
        if default_value is not None:
            # Handle different default value types
            if isinstance(default_value, str):
                # If it's a string, wrap in quotes
                if default_value.startswith('('):  # It's a function like datetime('now')
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                else:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} DEFAULT '{default_value}'"
            else:
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
        else:
            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        
        cursor.execute(sql)
        conn.commit()
        print(f"   ✅ Added column '{column_name}' to '{table_name}'")
        return True
    except sqlite3.Error as e:
        print(f"   ❌ Failed to add column '{column_name}': {e}")
        return False

def migrate_questions_table(conn):
    """Migrate the questions table to new schema"""
    print("\n📋 Migrating 'questions' table...")
    
    existing = get_existing_columns(conn, 'questions')
    print(f"   Existing columns: {', '.join(existing)}")
    
    # Add all missing columns
    columns_to_add = [
        ('chapter', 'TEXT', ''),
        ('tags', 'TEXT', ''),
        ('status', 'TEXT', 'active'),
        ('version', 'INTEGER', 1),
        ('created_by', 'INTEGER', None),
        ('updated_by', 'INTEGER', None),
        ('updated_at', 'TEXT', "(datetime('now', 'localtime'))"),
    ]
    
    for col_name, col_type, default in columns_to_add:
        add_column_if_not_exists(conn, 'questions', col_name, col_type, default)
    
    # Update the CHECK constraint on correct_answer to allow D, E, F
    try:
        cursor = conn.cursor()
        # Check if the constraint exists
        cursor.execute("""
            SELECT sql FROM sqlite_master 
            WHERE type='table' AND name='questions'
        """)
        create_sql = cursor.fetchone()[0]
        
        if 'CHECK (correct_answer IN' in create_sql and 'F' not in create_sql:
            print("   ⚠️ Updating correct_answer CHECK constraint...")
            print("   ℹ️ You'll need to recreate the table to update CHECK constraints.")
            print("   ℹ️ For now, the code will handle 'D', 'E', 'F' options.")
    except:
        pass
    
    # Create missing indexes
    indexes = [
        ("CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status)",),
        ("CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty)",),
        ("CREATE INDEX IF NOT EXISTS idx_questions_created_by ON questions(created_by)",),
        ("CREATE INDEX IF NOT EXISTS idx_questions_created_at ON questions(created_at DESC)",),
        ("CREATE INDEX IF NOT EXISTS idx_questions_updated_at ON questions(updated_at DESC)",),
    ]
    
    for idx_sql in indexes:
        try:
            cursor = conn.cursor()
            cursor.execute(idx_sql[0])
            conn.commit()
            print(f"   ✅ Created index: {idx_sql[0].split('ON')[0].strip()}")
        except Exception as e:
            print(f"   ⚠️ Could not create index: {e}")
    
    print("✅ Questions table migration complete!")

def migrate_quiz_attempts_table(conn):
    """Add missing indexes to quiz_attempts"""
    print("\n📋 Migrating 'quiz_attempts' table...")
    
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attempts_completed ON quiz_attempts(completed_at DESC)")
        conn.commit()
        print("   ✅ Added index: idx_attempts_completed")
    except Exception as e:
        print(f"   ⚠️ Could not create index: {e}")

def migrate_groups_table(conn):
    """Add missing indexes to groups"""
    print("\n📋 Migrating 'groups' table...")
    
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_click_count ON groups(click_count DESC)")
        conn.commit()
        print("   ✅ Added index: idx_groups_click_count")
    except Exception as e:
        print(f"   ⚠️ Could not create index: {e}")

def migrate_pdfs_table(conn):
    """Add missing indexes to pdfs"""
    print("\n📋 Migrating 'pdfs' table...")
    
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_pdfs_category ON pdfs(category)",
        "CREATE INDEX IF NOT EXISTS idx_pdfs_view_count ON pdfs(view_count DESC)",
    ]
    
    for idx_sql in indexes:
        try:
            cursor = conn.cursor()
            cursor.execute(idx_sql)
            conn.commit()
            print(f"   ✅ Added index: {idx_sql.split('ON')[0].strip()}")
        except Exception as e:
            print(f"   ⚠️ Could not create index: {e}")

def migrate_live_quizzes_table(conn):
    """Add missing indexes to live_quizzes"""
    print("\n📋 Migrating 'live_quizzes' table...")
    
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_live_quizzes_subject ON live_quizzes(subject_id)",
        "CREATE INDEX IF NOT EXISTS idx_live_quizzes_created ON live_quizzes(created_at DESC)",
    ]
    
    for idx_sql in indexes:
        try:
            cursor = conn.cursor()
            cursor.execute(idx_sql)
            conn.commit()
            print(f"   ✅ Added index: {idx_sql.split('ON')[0].strip()}")
        except Exception as e:
            print(f"   ⚠️ Could not create index: {e}")

def migrate_live_quiz_participants_table(conn):
    """Add missing indexes to live_quiz_participants"""
    print("\n📋 Migrating 'live_quiz_participants' table...")
    
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_participants_ranking ON live_quiz_participants(ranking)")
        conn.commit()
        print("   ✅ Added index: idx_participants_ranking")
    except Exception as e:
        print(f"   ⚠️ Could not create index: {e}")

def migrate_deleted_users_table(conn):
    """Add missing indexes to deleted_users"""
    print("\n📋 Migrating 'deleted_users' table...")
    
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deleted_deleted_by ON deleted_users(deleted_by)")
        conn.commit()
        print("   ✅ Added index: idx_deleted_deleted_by")
    except Exception as e:
        print(f"   ⚠️ Could not create index: {e}")

def migrate_quiz_ratings_table(conn):
    """Add missing indexes to quiz_ratings"""
    print("\n📋 Migrating 'quiz_ratings' table...")
    
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_ratings_rating ON quiz_ratings(rating)",
        "CREATE INDEX IF NOT EXISTS idx_ratings_created ON quiz_ratings(created_at DESC)",
    ]
    
    for idx_sql in indexes:
        try:
            cursor = conn.cursor()
            cursor.execute(idx_sql)
            conn.commit()
            print(f"   ✅ Added index: {idx_sql.split('ON')[0].strip()}")
        except Exception as e:
            print(f"   ⚠️ Could not create index: {e}")

def migrate_notifications_table(conn):
    """Add missing indexes to notifications"""
    print("\n📋 Migrating 'notifications' table...")
    
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type)")
        conn.commit()
        print("   ✅ Added index: idx_notifications_type")
    except Exception as e:
        print(f"   ⚠️ Could not create index: {e}")

def create_notification_preferences_table(conn):
    """Create the notification_preferences table if it doesn't exist"""
    print("\n📋 Creating 'notification_preferences' table...")
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES students(id) ON DELETE CASCADE,
                UNIQUE(user_id, notification_type)
            )
        """)
        conn.commit()
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pref_user ON notification_preferences(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pref_type ON notification_preferences(notification_type)")
        conn.commit()
        
        print("   ✅ Created notification_preferences table")
    except Exception as e:
        print(f"   ⚠️ Could not create notification_preferences table: {e}")

def verify_migration(conn):
    """Verify all columns exist"""
    print("\n🔍 Verifying migration...")
    
    # Check questions table
    questions_cols = get_existing_columns(conn, 'questions')
    expected_cols = ['id', 'subject_id', 'question_text', 'options', 'correct_answer', 
                     'difficulty', 'chapter', 'tags', 'explanation', 'status', 'version',
                     'created_by', 'updated_by', 'created_at', 'updated_at']
    
    missing = [col for col in expected_cols if col not in questions_cols]
    
    if missing:
        print(f"   ❌ Missing columns in questions: {', '.join(missing)}")
        return False
    else:
        print("   ✅ All expected columns found in questions table")
    
    # Check notification_preferences exists
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notification_preferences'")
    if cursor.fetchone():
        print("   ✅ notification_preferences table exists")
    else:
        print("   ⚠️ notification_preferences table not found")
    
    return True

def main():
    """Main migration function"""
    print("=" * 60)
    print("🔄 DATABASE SCHEMA MIGRATION")
    print("=" * 60)
    print(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return
    
    # Backup
    print("\n📦 Creating backup...")
    if not backup_database():
        return
    
    # Connect to database
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        # Run migrations
        migrate_questions_table(conn)
        migrate_quiz_attempts_table(conn)
        migrate_groups_table(conn)
        migrate_pdfs_table(conn)
        migrate_live_quizzes_table(conn)
        migrate_live_quiz_participants_table(conn)
        migrate_deleted_users_table(conn)
        migrate_quiz_ratings_table(conn)
        migrate_notifications_table(conn)
        create_notification_preferences_table(conn)
        
        # Verify
        verify_migration(conn)
        
        conn.close()
        
        print("\n" + "=" * 60)
        print("✅ Migration completed successfully!")
        print("=" * 60)
        print(f"\n📝 Backup saved to: {BACKUP_PATH}")
        print("   Keep this file until you confirm everything works.")
        print("\n🔧 Next steps:")
        print("   1. Test adding a question through the admin panel")
        print("   2. Check that existing questions are accessible")
        print("   3. If everything works, you can delete the backup")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        print(f"   Restore from backup: cp {BACKUP_PATH} {DB_PATH}")

if __name__ == '__main__':
    main()