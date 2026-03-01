"""
APEX SWARM - Database Migration: Smart Knowledge Columns
Run ONCE before deploying the smart knowledge update.

Usage:
    python3 migrate_knowledge.py

Safe to run multiple times — uses IF NOT EXISTS / try-except.
"""

import sqlite3
import os
import sys

DB_PATH = os.environ.get("DATABASE_PATH", "apex_swarm.db")


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if knowledge table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge'")
    if not cursor.fetchone():
        print("[INFO] Creating knowledge table from scratch...")
        cursor.execute("""
            CREATE TABLE knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT NOT NULL,
                domain TEXT DEFAULT '',
                created_at REAL DEFAULT (strftime('%s', 'now')),
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                times_used INTEGER DEFAULT 0,
                source_agent TEXT DEFAULT ''
            )
        """)
        print("[DONE] knowledge table created.")
    else:
        # Add new columns if they don't exist
        cursor.execute("PRAGMA table_info(knowledge)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        new_columns = {
            "domain": "TEXT DEFAULT ''",
            "created_at": "REAL DEFAULT (strftime('%s', 'now'))",
            "success_count": "INTEGER DEFAULT 0",
            "fail_count": "INTEGER DEFAULT 0",
            "times_used": "INTEGER DEFAULT 0",
            "source_agent": "TEXT DEFAULT ''",
        }

        for col_name, col_type in new_columns.items():
            if col_name not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE knowledge ADD COLUMN {col_name} {col_type}")
                    print(f"[DONE] Added column: {col_name}")
                except Exception as e:
                    print(f"[SKIP] Column {col_name}: {e}")
            else:
                print(f"[SKIP] Column {col_name} already exists")

    # Create indexes
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_domain ON knowledge(domain)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_created ON knowledge(created_at DESC)")
        print("[DONE] Indexes created")
    except Exception as e:
        print(f"[SKIP] Indexes: {e}")

    # Backfill: set created_at for rows that have NULL
    cursor.execute("UPDATE knowledge SET created_at = strftime('%s', 'now') WHERE created_at IS NULL OR created_at = 0")
    backfilled = cursor.rowcount
    if backfilled > 0:
        print(f"[DONE] Backfilled created_at for {backfilled} rows")

    conn.commit()
    conn.close()

    print(f"\n[SUCCESS] Migration complete on {DB_PATH}")
    print("You can now deploy with smart_knowledge.py")


if __name__ == "__main__":
    migrate()
