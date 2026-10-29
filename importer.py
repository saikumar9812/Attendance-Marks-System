import argparse
import sqlite3
import sys
from datetime import date

import pandas as pd

from db import DEFAULT_PASSWORD, get_connection, hash_password, init_db

IMPORT_ORDER = ["semesters", "teachers", "students", "subjects", "attendance", "marks"]

REQUIRED_COLUMNS = {
    "semesters": ["semester_id", "name", "start_date", "end_date"],
    "teachers": ["teacher_id", "name"],
    "students": ["student_id", "name"],
    "subjects": ["subject_code", "name", "credits", "semester_id", "teacher_id"],
    "attendance": ["student_id", "subject_code", "date", "status"],
    "marks": ["student_id", "subject_code", "assessment_type", "max_marks", "obtained"],
}

STATUS_MAP = {"present": "present", "p": "present", "1": "present",
              "absent": "absent", "a": "absent", "0": "absent"}


def _text(value):
    return "" if pd.isna(value) else str(value).strip()


def _iso_date(value):
    return date.fromisoformat(_text(value)).isoformat()


def _password_hash(row):
    return hash_password(_text(row.get("password")) or DEFAULT_PASSWORD)


def _row_to_params(kind, row):
    if kind == "semesters":
        return (_text(row["semester_id"]), _text(row["name"]),
                _iso_date(row["start_date"]), _iso_date(row["end_date"]))
    if kind == "teachers":
        return (_text(row["teacher_id"]), _text(row["name"]), _text(row.get("email")), _password_hash(row))
    if kind == "students":
        return (_text(row["student_id"]), _text(row["name"]), _text(row.get("email")),
                _text(row.get("program")), _password_hash(row))
    if kind == "subjects":
        return (_text(row["subject_code"]), _text(row["name"]), int(row["credits"]),
                _text(row["semester_id"]), _text(row["teacher_id"]) or None)
    if kind == "attendance":
        status = STATUS_MAP.get(_text(row["status"]).lower())
        if status is None:
            raise ValueError(f"invalid status '{row['status']}' (use present/absent)")
        return (_text(row["student_id"]), _text(row["subject_code"]), _iso_date(row["date"]), status)
    if kind == "marks":
        max_marks, obtained = float(row["max_marks"]), float(row["obtained"])
        if not 0 <= obtained <= max_marks:
            raise ValueError(f"obtained {obtained} outside 0..{max_marks}")
        return (_text(row["student_id"]), _text(row["subject_code"]),
                _text(row["assessment_type"]).lower(), max_marks, obtained)
    raise ValueError(f"unknown import type '{kind}'")


UPSERT_SQL = {
    "semesters": """INSERT INTO semesters VALUES (?, ?, ?, ?)
        ON CONFLICT(semester_id) DO UPDATE SET name=excluded.name,
        start_date=excluded.start_date, end_date=excluded.end_date""",
    "teachers": """INSERT INTO teachers VALUES (?, ?, ?, ?)
        ON CONFLICT(teacher_id) DO UPDATE SET name=excluded.name, email=excluded.email,
        password_hash=excluded.password_hash""",
    "students": """INSERT INTO students VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET name=excluded.name, email=excluded.email,
        program=excluded.program, password_hash=excluded.password_hash""",
    "subjects": """INSERT INTO subjects VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(subject_code) DO UPDATE SET name=excluded.name, credits=excluded.credits,
        semester_id=excluded.semester_id, teacher_id=excluded.teacher_id""",
    "attendance": """INSERT INTO attendance (student_id, subject_code, date, status) VALUES (?, ?, ?, ?)
        ON CONFLICT(student_id, subject_code, date) DO UPDATE SET status=excluded.status""",
    "marks": """INSERT INTO marks (student_id, subject_code, assessment_type, max_marks, obtained)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(student_id, subject_code, assessment_type) DO UPDATE SET
        max_marks=excluded.max_marks, obtained=excluded.obtained""",
}


def import_dataframe(conn, kind, df):
    if kind not in REQUIRED_COLUMNS:
        raise ValueError(f"unknown import type '{kind}'")
    df = df.rename(columns=lambda c: str(c).strip().lower())
    missing = [c for c in REQUIRED_COLUMNS[kind] if c not in df.columns]
    if missing:
        return 0, [f"missing required columns: {', '.join(missing)}"]
    imported, errors = 0, []
    for line_no, row in enumerate(df.to_dict("records"), start=2):
        try:
            conn.execute(UPSERT_SQL[kind], _row_to_params(kind, row))
            imported += 1
        except (ValueError, TypeError, sqlite3.IntegrityError) as exc:
            errors.append(f"line {line_no}: {exc}")
    conn.commit()
    return imported, errors


def import_csv(conn, kind, source):
    return import_dataframe(conn, kind, pd.read_csv(source, dtype=str, keep_default_na=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import a CSV file into the attendance DB.")
    parser.add_argument("kind", choices=IMPORT_ORDER)
    parser.add_argument("csv_path")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: attendance.db)")
    args = parser.parse_args(argv)
    conn = get_connection(args.db)
    init_db(conn)
    imported, errors = import_csv(conn, args.kind, args.csv_path)
    print(f"{args.kind}: imported {imported} rows, {len(errors)} errors")
    for err in errors[:20]:
        print("  " + err)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
