import hashlib
import os
import sqlite3
from pathlib import Path

import pandas as pd

ATTENDANCE_THRESHOLD = 75.0
DEFAULT_PASSWORD = "pass123"
DB_PATH = Path(os.environ.get("AMS_DB_PATH", Path(__file__).parent / "attendance.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS semesters (
    semester_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teachers (
    teacher_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS students (
    student_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT,
    program       TEXT,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subjects (
    subject_code TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    credits      INTEGER NOT NULL CHECK (credits > 0),
    semester_id  TEXT NOT NULL REFERENCES semesters(semester_id),
    teacher_id   TEXT REFERENCES teachers(teacher_id)
);
CREATE TABLE IF NOT EXISTS attendance (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT NOT NULL REFERENCES students(student_id),
    subject_code TEXT NOT NULL REFERENCES subjects(subject_code),
    date         TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('present', 'absent')),
    UNIQUE (student_id, subject_code, date)
);
CREATE TABLE IF NOT EXISTS marks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      TEXT NOT NULL REFERENCES students(student_id),
    subject_code    TEXT NOT NULL REFERENCES subjects(subject_code),
    assessment_type TEXT NOT NULL,
    max_marks       REAL NOT NULL CHECK (max_marks > 0),
    obtained        REAL NOT NULL CHECK (obtained >= 0 AND obtained <= max_marks),
    UNIQUE (student_id, subject_code, assessment_type)
);
CREATE INDEX IF NOT EXISTS idx_att_student ON attendance(student_id, subject_code);
CREATE INDEX IF NOT EXISTS idx_marks_student ON marks(student_id, subject_code);
"""

ASSESSMENT_ORDER = ["internal", "midterm", "final"]


def attendance_pct(present, total):
    if not total:
        return None
    return round(100.0 * present / total, 2)


def is_below_threshold(pct, threshold=ATTENDANCE_THRESHOLD):
    return pct is not None and not pd.isna(pct) and pct < threshold


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_connection(db_path=None):
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def reset_db(conn):
    conn.executescript(
        "DROP TABLE IF EXISTS marks; DROP TABLE IF EXISTS attendance; DROP TABLE IF EXISTS subjects;"
        "DROP TABLE IF EXISTS students; DROP TABLE IF EXISTS teachers; DROP TABLE IF EXISTS semesters;"
    )
    init_db(conn)


def table_counts(conn):
    tables = ["semesters", "teachers", "students", "subjects", "attendance", "marks"]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def verify_login(conn, role, user_id, password):
    table, key = ("students", "student_id") if role == "student" else ("teachers", "teacher_id")
    row = conn.execute(f"SELECT password_hash FROM {table} WHERE {key} = ?", (user_id,)).fetchone()
    return row is not None and row["password_hash"] == hash_password(password)


def _df(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


def list_students(conn):
    return _df(conn, "SELECT student_id, name, email, program FROM students ORDER BY student_id")


def list_teachers(conn):
    return _df(conn, "SELECT teacher_id, name, email FROM teachers ORDER BY teacher_id")


def list_semesters(conn):
    return _df(conn, "SELECT semester_id, name, start_date, end_date FROM semesters ORDER BY start_date")


def list_subjects(conn, semester_id=None):
    sql = """
        SELECT s.subject_code, s.name, s.credits, s.semester_id, sem.name AS semester,
               s.teacher_id, t.name AS teacher
        FROM subjects s
        JOIN semesters sem ON sem.semester_id = s.semester_id
        LEFT JOIN teachers t ON t.teacher_id = s.teacher_id
        WHERE (? IS NULL OR s.semester_id = ?)
        ORDER BY sem.start_date, s.subject_code
    """
    return _df(conn, sql, (semester_id, semester_id))


def subject_summary(conn, student_id=None, semester_id=None):
    sql = """
        WITH att AS (
            SELECT student_id, subject_code,
                   SUM(status = 'present') AS present, COUNT(*) AS total_classes
            FROM attendance GROUP BY student_id, subject_code
        ),
        mk AS (
            SELECT student_id, subject_code,
                   SUM(obtained) AS marks_obtained, SUM(max_marks) AS marks_max
            FROM marks GROUP BY student_id, subject_code
        )
        SELECT st.student_id, st.name AS student_name,
               sub.subject_code, sub.name AS subject_name, sub.credits,
               sub.semester_id, sem.name AS semester, sub.teacher_id,
               COALESCE(att.present, 0) AS present,
               COALESCE(att.total_classes, 0) AS total_classes,
               mk.marks_obtained, mk.marks_max
        FROM students st
        CROSS JOIN subjects sub
        JOIN semesters sem ON sem.semester_id = sub.semester_id
        LEFT JOIN att ON att.student_id = st.student_id AND att.subject_code = sub.subject_code
        LEFT JOIN mk ON mk.student_id = st.student_id AND mk.subject_code = sub.subject_code
        WHERE (att.total_classes IS NOT NULL OR mk.marks_max IS NOT NULL)
          AND (? IS NULL OR st.student_id = ?)
          AND (? IS NULL OR sub.semester_id = ?)
        ORDER BY st.student_id, sem.start_date, sub.subject_code
    """
    df = _df(conn, sql, (student_id, student_id, semester_id, semester_id))
    df["attendance_pct"] = [attendance_pct(p, t) for p, t in zip(df["present"], df["total_classes"])]
    df["marks_pct"] = [
        round(100.0 * o / m, 2) if pd.notna(m) and m else None
        for o, m in zip(df["marks_obtained"], df["marks_max"])
    ]
    df["below_threshold"] = df["attendance_pct"].apply(is_below_threshold)
    return df


def overall_summary(summary_df):
    """Aggregate a subject_summary frame to one row per student (class-weighted, not averaged %)."""
    cols = ["student_id", "student_name", "present", "total_classes", "marks_obtained",
            "marks_max", "overall_attendance_pct", "overall_marks_pct", "below_threshold"]
    if summary_df.empty:
        return pd.DataFrame(columns=cols)
    g = summary_df.groupby(["student_id", "student_name"], as_index=False).agg(
        present=("present", "sum"),
        total_classes=("total_classes", "sum"),
        marks_obtained=("marks_obtained", "sum"),
        marks_max=("marks_max", "sum"),
    )
    g["overall_attendance_pct"] = [attendance_pct(p, t) for p, t in zip(g["present"], g["total_classes"])]
    g["overall_marks_pct"] = [
        round(100.0 * o / m, 2) if m else None for o, m in zip(g["marks_obtained"], g["marks_max"])
    ]
    g["below_threshold"] = g["overall_attendance_pct"].apply(is_below_threshold)
    return g[cols]


def student_marks(conn, student_id, semester_id=None):
    sql = """
        SELECT m.subject_code, s.name AS subject_name, s.semester_id, m.assessment_type,
               m.max_marks, m.obtained, ROUND(100.0 * m.obtained / m.max_marks, 2) AS pct
        FROM marks m JOIN subjects s ON s.subject_code = m.subject_code
        WHERE m.student_id = ? AND (? IS NULL OR s.semester_id = ?)
        ORDER BY s.subject_code, CASE m.assessment_type
            WHEN 'internal' THEN 1 WHEN 'midterm' THEN 2 WHEN 'final' THEN 3 ELSE 4 END
    """
    return _df(conn, sql, (student_id, semester_id, semester_id))


def class_marks(conn, semester_id=None):
    sql = """
        SELECT m.student_id, m.subject_code, m.assessment_type, m.max_marks, m.obtained
        FROM marks m JOIN subjects s ON s.subject_code = m.subject_code
        WHERE (? IS NULL OR s.semester_id = ?)
    """
    return _df(conn, sql, (semester_id, semester_id))


def student_attendance_log(conn, student_id, subject_code):
    sql = """
        SELECT date, status FROM attendance
        WHERE student_id = ? AND subject_code = ? ORDER BY date
    """
    return _df(conn, sql, (student_id, subject_code))
