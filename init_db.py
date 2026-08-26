#!/usr/bin/env python3
"""
Database Initialization Script
Run this once to create the database schema.
"""

import sqlite3
import os

DB_PATH = 'nuunplatform.db'
SCHEMA_PATH = 'schema.sql'

def init_database():
    """Initialize the database with schema.sql"""
    print("🔧 Initializing database...")
    
    try:
        # Check if schema file exists
        if not os.path.exists(SCHEMA_PATH):
            print(f"❌ schema.sql not found at {SCHEMA_PATH}")
            return False
        
        # Connect to database (creates file if it doesn't exist)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Read and execute schema
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        
        cursor.executescript(schema_sql)
        conn.commit()
        conn.close()
        
        print(f"✅ Database initialized successfully at {DB_PATH}")
        return True
        
    except sqlite3.Error as e:
        print(f"❌ SQLite error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == '__main__':
    init_database()