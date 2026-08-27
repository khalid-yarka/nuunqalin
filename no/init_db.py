#!/usr/bin/env python3
"""Initialize database with admin and 3 subjects"""

import sqlite3
import secrets
import string
from datetime import datetime, timezone, timedelta

DB_PATH = 'nuunplatform.db'
SCHEMA_PATH = 'schema.sql'

def now():
    tz = timezone(timedelta(hours=3))
    return datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')

def generate_id():
    return ''.join(secrets.choice(string.ascii_uppercase + '123456789') for _ in range(4))

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Create tables
with open(SCHEMA_PATH) as f:
    cursor.executescript(f.read())

# Create admin
cursor.execute("SELECT id FROM students WHERE is_admin=1")
if not cursor.fetchone():
    pid = generate_id()
    cursor.execute("""
        INSERT INTO students (public_id, phone_number, password, first_name, last_name, is_admin, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (pid, '+252906500599', 'Nuuniloveu', 'Khalid', 'Ahmed', 1, now()))
    print(f"✅ Admin created: +252611223344 / admin123")

# Create subjects
for name in ['Arabic', 'Somali', 'Geography']:
    cursor.execute("SELECT id FROM subjects WHERE name=?", (name,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO subjects (name, created_at) VALUES (?, ?)", (name, now()))
        print(f"✅ Subject added: {name}")

conn.commit()
conn.close()
print("✅ Database ready!")