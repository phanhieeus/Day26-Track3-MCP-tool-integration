"""Create and seed the SQLite database used by the lab MCP server.

Run directly to (re)create the database:

    python init_db.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "lab.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS students (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    email   TEXT NOT NULL UNIQUE,
    cohort  TEXT NOT NULL,
    score   REAL
);

CREATE TABLE IF NOT EXISTS courses (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    code    TEXT NOT NULL UNIQUE,
    title   TEXT NOT NULL,
    credits INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS enrollments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    course_id  INTEGER NOT NULL REFERENCES courses(id),
    grade      REAL,
    UNIQUE (student_id, course_id)
);
"""

SEED_SQL = """
INSERT INTO students (name, email, cohort, score) VALUES
    ('An Nguyen',    'an.nguyen@example.com',    'A1', 8.5),
    ('Binh Tran',    'binh.tran@example.com',    'A1', 7.2),
    ('Chi Le',       'chi.le@example.com',       'A2', 9.1),
    ('Dung Pham',    'dung.pham@example.com',    'A2', 6.8),
    ('Giang Hoang',  'giang.hoang@example.com',  'B1', 8.9),
    ('Huy Vo',       'huy.vo@example.com',       'B1', 7.7);

INSERT INTO courses (code, title, credits) VALUES
    ('CS101', 'Introduction to Programming', 3),
    ('CS201', 'Data Structures',             4),
    ('AI301', 'Machine Learning',            4);

INSERT INTO enrollments (student_id, course_id, grade) VALUES
    (1, 1, 8.0),
    (1, 2, 8.7),
    (2, 1, 7.0),
    (3, 2, 9.5),
    (3, 3, 9.0),
    (4, 1, 6.5),
    (5, 3, 9.2),
    (6, 2, 7.4);
"""


def create_database(db_path: str | Path = DB_PATH, force: bool = True) -> Path:
    """Create the database file with schema and seed data.

    With ``force=True`` (default) any existing file is removed first so the
    result is reproducible. With ``force=False`` an existing database is
    kept as-is.
    """
    db_path = Path(db_path)
    if db_path.exists():
        if not force:
            return db_path
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SEED_SQL)
        conn.commit()
    finally:
        conn.close()
    return db_path


if __name__ == "__main__":
    path = create_database()
    print(f"Database created at {path}")
