-- ============================================
-- NUUNPLATFORM DATABASE SCHEMA (COMPLETE)
-- ============================================

-- ============================================
-- STUDENTS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS students (
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
);

CREATE INDEX IF NOT EXISTS idx_students_phone ON students(phone_number);
CREATE INDEX IF NOT EXISTS idx_students_public_id ON students(public_id);

-- ============================================
-- SUBJECTS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    icon TEXT DEFAULT '📚',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- ============================================
-- QUESTIONS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    options TEXT NOT NULL,
    correct_answer TEXT NOT NULL CHECK (correct_answer IN ('A', 'B', 'C', 'D', 'E', 'F')),
    difficulty INTEGER DEFAULT 1,
    chapter TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    explanation TEXT DEFAULT '',
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'archived', 'draft')),
    version INTEGER DEFAULT 1,
    created_by INTEGER,
    updated_by INTEGER,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES students(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by) REFERENCES students(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject_id);
CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status);
CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty);
CREATE INDEX IF NOT EXISTS idx_questions_created_by ON questions(created_by);
CREATE INDEX IF NOT EXISTS idx_questions_created_at ON questions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_questions_updated_at ON questions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_questions_subject_status ON questions(subject_id, status);

-- ============================================
-- QUIZ ATTEMPTS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS quiz_attempts (
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
);

CREATE INDEX IF NOT EXISTS idx_attempts_student ON quiz_attempts(student_id);
CREATE INDEX IF NOT EXISTS idx_attempts_subject ON quiz_attempts(subject_id);
CREATE INDEX IF NOT EXISTS idx_attempts_completed ON quiz_attempts(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student_completed ON quiz_attempts(student_id, completed_at DESC);

-- ============================================
-- GROUPS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('whatsapp', 'telegram')),
    invite_link TEXT NOT NULL,
    description TEXT DEFAULT '',
    category TEXT DEFAULT '',
    click_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_groups_platform ON groups(platform);
CREATE INDEX IF NOT EXISTS idx_groups_category ON groups(category);
CREATE INDEX IF NOT EXISTS idx_groups_active ON groups(is_active);
CREATE INDEX IF NOT EXISTS idx_groups_click_count ON groups(click_count DESC);

-- ============================================
-- PDFS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS pdfs (
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
);

CREATE INDEX IF NOT EXISTS idx_pdfs_subject ON pdfs(subject);
CREATE INDEX IF NOT EXISTS idx_pdfs_grade ON pdfs(grade);
CREATE INDEX IF NOT EXISTS idx_pdfs_category ON pdfs(category);
CREATE INDEX IF NOT EXISTS idx_pdfs_view_count ON pdfs(view_count DESC);

-- ============================================
-- LIVE QUIZZES TABLE (with scheduling)
-- ============================================

CREATE TABLE IF NOT EXISTS live_quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL,
    title TEXT DEFAULT '',
    subject_id INTEGER NOT NULL,
    question_count INTEGER DEFAULT 10,
    join_code TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'waiting' CHECK (status IN ('waiting', 'scheduled', 'active', 'finished')),
    max_participants INTEGER DEFAULT 50,
    time_per_question INTEGER DEFAULT 30,
    current_question_index INTEGER DEFAULT 0,
    question_ids TEXT,
    started_at TEXT,
    ended_at TEXT,
    scheduled_start TEXT,
    is_public INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (creator_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_live_quizzes_code ON live_quizzes(join_code);
CREATE INDEX IF NOT EXISTS idx_live_quizzes_status ON live_quizzes(status);
CREATE INDEX IF NOT EXISTS idx_live_quizzes_creator ON live_quizzes(creator_id);
CREATE INDEX IF NOT EXISTS idx_live_quizzes_subject ON live_quizzes(subject_id);
CREATE INDEX IF NOT EXISTS idx_live_quizzes_created ON live_quizzes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_live_quizzes_scheduled ON live_quizzes(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_live_quizzes_status_created ON live_quizzes(status, created_at DESC);

-- ============================================
-- LIVE QUIZ PARTICIPANTS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS live_quiz_participants (
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
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'completed', 'left')),
    is_ready INTEGER DEFAULT 0,
    joined_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (quiz_id) REFERENCES live_quizzes(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    UNIQUE(quiz_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_participants_quiz ON live_quiz_participants(quiz_id);
CREATE INDEX IF NOT EXISTS idx_participants_student ON live_quiz_participants(student_id);
CREATE INDEX IF NOT EXISTS idx_participants_score ON live_quiz_participants(score DESC);
CREATE INDEX IF NOT EXISTS idx_participants_ranking ON live_quiz_participants(ranking);
CREATE INDEX IF NOT EXISTS idx_live_quiz_participants_quiz_score ON live_quiz_participants(quiz_id, score DESC);

-- ============================================
-- DELETED USERS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS deleted_users (
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
);

CREATE INDEX IF NOT EXISTS idx_deleted_public_id ON deleted_users(public_id);
CREATE INDEX IF NOT EXISTS idx_deleted_at ON deleted_users(deleted_at DESC);
CREATE INDEX IF NOT EXISTS idx_deleted_deleted_by ON deleted_users(deleted_by);

-- ============================================
-- QUIZ RATINGS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS quiz_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('HAA', 'MAY')),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ratings_student ON quiz_ratings(student_id);
CREATE INDEX IF NOT EXISTS idx_ratings_question ON quiz_ratings(question_id);
CREATE INDEX IF NOT EXISTS idx_ratings_rating ON quiz_ratings(rating);
CREATE INDEX IF NOT EXISTS idx_ratings_created ON quiz_ratings(created_at DESC);

-- ============================================
-- NOTIFICATIONS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT DEFAULT '',
    icon TEXT DEFAULT '',
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    read_at TEXT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES students(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);

-- ============================================
-- NOTIFICATION PREFERENCES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS notification_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    notification_type TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES students(id) ON DELETE CASCADE,
    UNIQUE(user_id, notification_type)
);

CREATE INDEX IF NOT EXISTS idx_pref_user ON notification_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_pref_type ON notification_preferences(notification_type);

-- ============================================
-- ACTIVITY LOGS (Audit Trail) – NEW
-- ============================================

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    session_id TEXT,
    activity_type TEXT NOT NULL,
    severity TEXT DEFAULT 'info' CHECK (severity IN ('info', 'warning', 'critical')),
    message TEXT NOT NULL,
    metadata TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES students(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_type ON activity_logs(activity_type);

-- ============================================
-- BACKUP CONFIGURATION – NEW
-- ============================================

CREATE TABLE IF NOT EXISTS backup_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    daily_retention INTEGER DEFAULT 7,
    weekly_retention INTEGER DEFAULT 4,
    monthly_retention INTEGER DEFAULT 12,
    scheduled_enabled INTEGER DEFAULT 0,
    scheduled_type TEXT DEFAULT 'daily',
    scheduled_time TEXT DEFAULT '02:00',
    last_modified TEXT DEFAULT (datetime('now', 'localtime'))
);

INSERT OR IGNORE INTO backup_config (id) VALUES (1);

-- ============================================
-- BACKUP OPERATIONS LOG – NEW
-- ============================================

CREATE TABLE IF NOT EXISTS backup_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_type TEXT NOT NULL,
    backup_filename TEXT,
    triggered_by INTEGER,
    status TEXT CHECK (status IN ('started', 'success', 'failed')),
    message TEXT,
    started_at TEXT DEFAULT (datetime('now', 'localtime')),
    completed_at TEXT,
    FOREIGN KEY (triggered_by) REFERENCES students(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_backup_ops_started ON backup_operations(started_at DESC);

-- ============================================
-- USER SETTINGS (Per‑User Preferences)
-- ============================================
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    settings JSON NOT NULL DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- ============================================
-- ADDITIONAL PERFORMANCE INDEXES
-- ============================================

CREATE INDEX IF NOT EXISTS idx_live_quiz_participants_quiz_score ON live_quiz_participants(quiz_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student_completed ON quiz_attempts(student_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_live_quizzes_status_created ON live_quizzes(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_questions_subject_status ON questions(subject_id, status);

