# create_admin.py - Complete Database Setup (All-in-One)

import sqlite3
import os
import secrets
import string
from datetime import datetime, timezone, timedelta

# ============================================
# CONSTANTS
# ============================================

DB_PATH = 'nuunplatform.db'
PUBLIC_ID_CHARS = string.ascii_uppercase + '123456789'
SOMALI_TZ = timezone(timedelta(hours=3))

# Admin credentials
ADMIN_PHONE = '+2521234567'
ADMIN_PASSWORD = 'admin123'
ADMIN_FIRST_NAME = 'admin'
ADMIN_MIDDLE_NAME = 'User'
ADMIN_LAST_NAME = 'user'
ADMIN_LOCATION = 'PL'
ADMIN_CITY = 'Bosaso'
ADMIN_SCHOOL = 'Imamu Nawawi Bosaso'
ADMIN_GRADE = 'Sare 4aad'

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_somali_time():
    return datetime.now(timezone(timedelta(hours=3)))

def now():
    return get_somali_time().isoformat()

def get_time_display():
    dt = get_somali_time()
    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    am_pm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.year}/{dt.month}/{dt.day} {hour}:{dt.minute:02d} {am_pm}"

def generate_public_id():
    return ''.join(secrets.choice(PUBLIC_ID_CHARS) for _ in range(4))


# ============================================
# SCHEMA - Each table as a separate string
# ============================================

def get_schema_statements():
    """Return a list of individual CREATE TABLE statements"""
    return [
        # STUDENTS
        """CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id TEXT UNIQUE NOT NULL,
            phone_number TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            first_name TEXT NOT NULL,
            middle_name TEXT DEFAULT '',
            last_name TEXT NOT NULL,
            location TEXT DEFAULT '',
            city TEXT DEFAULT '',
            school TEXT DEFAULT '',
            grade TEXT DEFAULT '',
            total_points INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_students_phone ON students(phone_number)""",
        """CREATE INDEX IF NOT EXISTS idx_students_public_id ON students(public_id)""",
        
        # SUBJECTS
        """CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            icon TEXT DEFAULT '📚',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        
        # QUESTIONS
        """CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            options TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            difficulty INTEGER DEFAULT 1,
            explanation TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject_id)""",
        
        # QUIZ ATTEMPTS
        """CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            score INTEGER DEFAULT 0,
            total_questions INTEGER DEFAULT 0,
            answers TEXT,
            ratings TEXT,
            completed_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_attempts_student ON quiz_attempts(student_id)""",
        """CREATE INDEX IF NOT EXISTS idx_attempts_subject ON quiz_attempts(subject_id)""",
        
        # GROUPS
        """CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            platform TEXT NOT NULL,
            invite_link TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            click_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_groups_platform ON groups(platform)""",
        """CREATE INDEX IF NOT EXISTS idx_groups_category ON groups(category)""",
        """CREATE INDEX IF NOT EXISTS idx_groups_active ON groups(is_active)""",
        
        # PDFS
        """CREATE TABLE IF NOT EXISTS pdfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            file_url TEXT NOT NULL,
            telegram_download_url TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            grade TEXT DEFAULT '',
            category TEXT DEFAULT '',
            view_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_pdfs_subject ON pdfs(subject)""",
        """CREATE INDEX IF NOT EXISTS idx_pdfs_grade ON pdfs(grade)""",
        
        # LIVE QUIZZES
        """CREATE TABLE IF NOT EXISTS live_quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            title TEXT DEFAULT '',
            subject_id INTEGER NOT NULL,
            question_count INTEGER DEFAULT 10,
            join_code TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'waiting',
            max_participants INTEGER DEFAULT 50,
            time_per_question INTEGER DEFAULT 30,
            current_question_index INTEGER DEFAULT 0,
            question_ids TEXT,
            started_at TEXT,
            ended_at TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (creator_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_live_quizzes_code ON live_quizzes(join_code)""",
        """CREATE INDEX IF NOT EXISTS idx_live_quizzes_status ON live_quizzes(status)""",
        """CREATE INDEX IF NOT EXISTS idx_live_quizzes_creator ON live_quizzes(creator_id)""",
        
        # LIVE QUIZ PARTICIPANTS
        """CREATE TABLE IF NOT EXISTS live_quiz_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            score INTEGER DEFAULT 0,
            current_question_index INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            skipped_count INTEGER DEFAULT 0,
            answers TEXT,
            ratings TEXT,
            ranking INTEGER,
            status TEXT DEFAULT 'active',
            joined_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (quiz_id) REFERENCES live_quizzes(id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            UNIQUE(quiz_id, student_id)
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_participants_quiz ON live_quiz_participants(quiz_id)""",
        """CREATE INDEX IF NOT EXISTS idx_participants_student ON live_quiz_participants(student_id)""",
        """CREATE INDEX IF NOT EXISTS idx_participants_score ON live_quiz_participants(score DESC)""",
        
        # DELETED USERS
        """CREATE TABLE IF NOT EXISTS deleted_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_id INTEGER,
            public_id TEXT,
            first_name TEXT,
            last_name TEXT,
            phone_number TEXT,
            school TEXT,
            grade TEXT,
            total_points INTEGER,
            is_admin INTEGER,
            location TEXT,
            city TEXT,
            deleted_by INTEGER,
            data TEXT NOT NULL,
            deleted_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (deleted_by) REFERENCES students(id) ON DELETE SET NULL
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_deleted_public_id ON deleted_users(public_id)""",
        """CREATE INDEX IF NOT EXISTS idx_deleted_at ON deleted_users(deleted_at DESC)""",
        
        # QUIZ RATINGS
        """CREATE TABLE IF NOT EXISTS quiz_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            rating TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        )""",
        
        """CREATE INDEX IF NOT EXISTS idx_ratings_student ON quiz_ratings(student_id)""",
        """CREATE INDEX IF NOT EXISTS idx_ratings_question ON quiz_ratings(question_id)"""
    ]


# ============================================
# CREATE DATABASE
# ============================================

def create_database():
    """Create the database with all tables"""
    print("\n" + "=" * 50)
    print("   🗄️  CREATING DATABASE")
    print("=" * 50)

    # Remove existing database if it exists
    if os.path.exists(DB_PATH):
        print(f"⚠️ Database '{DB_PATH}' exists. Deleting...")
        os.remove(DB_PATH)
        print("✅ Old database removed.")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Enable foreign keys and WAL mode
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")

        # Get all schema statements
        statements = get_schema_statements()
        created_tables = []

        # Execute each statement
        for stmt in statements:
            try:
                cursor.execute(stmt)
                if stmt.strip().upper().startswith('CREATE TABLE'):
                    # Extract table name
                    table_name = stmt.split('(')[0].replace('CREATE TABLE', '').replace('IF NOT EXISTS', '').strip()
                    if table_name not in created_tables:
                        created_tables.append(table_name)
                        print(f"   ✅ Created: {table_name}")
            except sqlite3.Error as e:
                print(f"   ⚠️ Warning: {e}")

        conn.commit()
        conn.close()

        print(f"\n✅ Database created successfully! ({len(created_tables)} tables)")
        return True

    except sqlite3.Error as e:
        print(f"❌ Error creating database: {e}")
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        return False


# ============================================
# CREATE ADMIN
# ============================================

def create_admin():
    """Create the admin user"""
    print("\n" + "=" * 50)
    print("   👤 CREATING ADMIN USER")
    print("=" * 50)

    if not os.path.exists(DB_PATH):
        print("❌ Database not found! Please create the database first.")
        return False

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check if admin already exists
        cursor.execute("SELECT * FROM students WHERE is_admin = 1")
        existing_admin = cursor.fetchone()
        
        if existing_admin:
            print("👤 Admin user already exists!")
            print("\n📋 Existing Admin Credentials:")
            print(f"   📞 Phone: {existing_admin[2]}")
            print(f"   🔑 Password: {existing_admin[3]}")
            print(f"   🆔 Public ID: {existing_admin[1]}")
            conn.close()
            return True

        # Generate a unique public ID
        public_id = generate_public_id()

        # Insert admin user
        cursor.execute("""
            INSERT INTO students (
                public_id, phone_number, password, first_name,
                middle_name, last_name, location, city, school, grade,
                total_points, is_admin, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            public_id,
            ADMIN_PHONE,
            ADMIN_PASSWORD,
            ADMIN_FIRST_NAME,
            ADMIN_MIDDLE_NAME,
            ADMIN_LAST_NAME,
            ADMIN_LOCATION,
            ADMIN_CITY,
            ADMIN_SCHOOL,
            ADMIN_GRADE,
            0,  # total_points
            1,  # is_admin
            now()
        ))
        
        conn.commit()
        conn.close()

        print("✅ Admin user created successfully!")
        print("\n📋 Admin Login Credentials:")
        print(f"   📞 Phone: {ADMIN_PHONE}")
        print(f"   🔑 Password: {ADMIN_PASSWORD}")
        print(f"   🆔 Public ID: {public_id}")
        print(f"   👤 Name: {ADMIN_FIRST_NAME} {ADMIN_MIDDLE_NAME} {ADMIN_LAST_NAME}")
        
        return True

    except sqlite3.IntegrityError as e:
        print(f"❌ Integrity Error: {e}")
        if 'UNIQUE constraint failed' in str(e):
            print("   💡 The admin phone number might already exist in the database.")
        return False
    except sqlite3.Error as e:
        print(f"❌ Database Error: {e}")
        return False


# ============================================
# VERIFY DATABASE
# ============================================

def verify_database():
    """Verify all tables were created correctly"""
    print("\n" + "=" * 50)
    print("   🔍 VERIFYING DATABASE")
    print("=" * 50)

    expected_tables = [
        'students', 'subjects', 'questions', 'quiz_attempts',
        'groups', 'pdfs', 'live_quizzes', 'live_quiz_participants',
        'deleted_users', 'quiz_ratings'
    ]

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        existing_tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        all_exist = True
        for table in expected_tables:
            if table in existing_tables:
                print(f"   ✅ {table}")
            else:
                print(f"   ❌ {table} (MISSING!)")
                all_exist = False

        if all_exist:
            print("\n✅ All tables verified successfully!")
        else:
            print("\n⚠️ Some tables are missing!")

        return all_exist

    except sqlite3.Error as e:
        print(f"❌ Error verifying database: {e}")
        return False


# ============================================
# SHOW DATABASE INFO
# ============================================

def show_database_info():
    """Show information about the database"""
    if not os.path.exists(DB_PATH):
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Get table counts
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        print("\n" + "=" * 50)
        print("   📊 DATABASE INFORMATION")
        print("=" * 50)
        print(f"   📁 Database: {DB_PATH}")
        print(f"   📏 Size: {os.path.getsize(DB_PATH) / 1024:.2f} KB")
        print(f"   📋 Tables: {len(tables)}")
        
        # Show admin info
        cursor.execute("SELECT phone_number, public_id, first_name, last_name FROM students WHERE is_admin = 1")
        admin = cursor.fetchone()
        if admin:
            print(f"\n   👤 Admin User:")
            print(f"      📞 Phone: {admin[0]}")
            print(f"      🆔 ID: {admin[1]}")
            print(f"      👤 Name: {admin[2]} {admin[3]}")
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"❌ Error: {e}")


# ============================================
# MAIN FUNCTION
# ============================================

def main():
    print("\n" + "█" * 50)
    print("   🚀 NUUNPLATFORM DATABASE SETUP")
    print("█" * 50)
    print(f"   Time: {get_time_display()}")
    print("█" * 50)

    # Check if database already exists
    if os.path.exists(DB_PATH):
        print(f"\n⚠️ Database '{DB_PATH}' already exists.")
        response = input("   Do you want to delete and recreate it? (y/n): ")
        if response.lower() != 'y':
            print("\n❌ Setup cancelled.")
            return
        print("\n🔄 Recreating database...")

    # Create database
    if not create_database():
        print("\n❌ Failed to create database. Exiting.")
        return

    # Verify tables
    verify_database()

    # Create admin user
    create_admin()

    # Show database info
    show_database_info()

    # Summary
    print("\n" + "=" * 50)
    print("   ✅ SETUP COMPLETE!")
    print("=" * 50)
    print("\n📋 Next steps:")
    print("   1. Run: python app.py")
    print("   2. Login with:")
    print(f"      📞 Phone: {ADMIN_PHONE}")
    print(f"      🔑 Password: {ADMIN_PASSWORD}")
    print(f"\n   🕐 Completed at: {get_time_display()}")


# ============================================
# SCRIPT ENTRY POINT
# ============================================

if __name__ == '__main__':
    main()