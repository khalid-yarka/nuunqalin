# ============================================
# PENDING PDF FUNCTIONS (for Telegram bot)
# ============================================

def ensure_pending_pdfs_table():
    """Create pending_pdfs table if not exists."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_pdfs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                file_unique_id TEXT UNIQUE NOT NULL,
                filename TEXT,
                uploaded_by INTEGER,
                uploaded_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_pdfs_uploaded_at ON pending_pdfs(uploaded_at DESC)")
        conn.commit()
        logger.info("pending_pdfs table verified/created")
        return True
    except Exception as e:
        logger.error(f"Failed to create pending_pdfs table: {e}")
        return False

def insert_pending_pdf(file_id, file_unique_id, filename, uploaded_by):
    """Insert a new pending PDF record and return its ID."""
    try:
        cursor = execute_with_retry("""
            INSERT INTO pending_pdfs (file_id, file_unique_id, filename, uploaded_by)
            VALUES (?, ?, ?, ?)
        """, (file_id, file_unique_id, filename, uploaded_by), commit=True)
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to insert pending PDF: {e}")
        return 0

def get_pending_pdf_by_id(pending_id):
    cursor = execute_with_retry("SELECT * FROM pending_pdfs WHERE id = ?", (pending_id,))
    row = cursor.fetchone()
    return dict(row) if row else None

def get_pending_pdfs(limit=50, offset=0):
    cursor = execute_with_retry("""
        SELECT * FROM pending_pdfs
        ORDER BY uploaded_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    return [dict(row) for row in cursor.fetchall()]

def count_pending_pdfs():
    cursor = execute_with_retry("SELECT COUNT(*) as count FROM pending_pdfs")
    row = cursor.fetchone()
    return row['count'] if row else 0

def delete_pending_pdf(pending_id):
    try:
        execute_with_retry("DELETE FROM pending_pdfs WHERE id = ?", (pending_id,), commit=True)
        return True
    except Exception:
        return False

def is_duplicate_pdf(file_unique_id):
    """Check if a PDF with this file_unique_id exists in pending_pdfs or pdfs."""
    cursor = execute_with_retry("SELECT id FROM pending_pdfs WHERE file_unique_id = ?", (file_unique_id,))
    if cursor.fetchone():
        return True
    cursor = execute_with_retry("SELECT id FROM pdfs WHERE file_unique_id = ?", (file_unique_id,))
    if cursor.fetchone():
        return True
    return False

def move_pending_to_pdfs(pending_id, pdf_data):
    """
    Atomically move a pending PDF to the pdfs table.
    pdf_data must contain: title, description, subject, grade, category,
    chapters, tags, is_premium, file_url, telegram_download_url, file_unique_id.
    """
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Check if pending still exists
        cursor = conn.execute("SELECT * FROM pending_pdfs WHERE id = ?", (pending_id,))
        pending = cursor.fetchone()
        if not pending:
            conn.rollback()
            return False, "Pending record not found"
        # Check duplicate in pdfs
        cursor = conn.execute("SELECT id FROM pdfs WHERE file_unique_id = ?", (pdf_data['file_unique_id'],))
        if cursor.fetchone():
            conn.rollback()
            return False, "Duplicate PDF already in pdfs"
        # Insert into pdfs
        cursor = conn.execute("""
            INSERT INTO pdfs (
                title, description, subject, grade, category, chapters, tags,
                is_premium, file_url, telegram_download_url, file_unique_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        """, (
            pdf_data['title'],
            pdf_data.get('description', ''),
            pdf_data['subject'],
            pdf_data['grade'],
            pdf_data.get('category', ''),
            pdf_data.get('chapters', ''),
            pdf_data.get('tags', ''),
            pdf_data.get('is_premium', 0),
            pdf_data['file_url'],
            pdf_data['telegram_download_url'],
            pdf_data['file_unique_id']
        ))
        new_pdf_id = cursor.lastrowid
        conn.execute("DELETE FROM pending_pdfs WHERE id = ?", (pending_id,))
        conn.commit()
        return True, new_pdf_id
    except Exception as e:
        conn.rollback()
        logger.error(f"move_pending_to_pdfs failed: {e}")
        return False, str(e)