import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from db import get_connection, reset_db, table_counts
from importer import IMPORT_ORDER, import_csv

DATA_DIR = Path(__file__).parent / "data"

SEMESTERS = [
    ("SEM3", "Semester 3 (Jan-May 2026)", "2026-01-05", "2026-05-15", "2026-04-30"),
    ("SEM4", "Semester 4 (Jul-Nov 2026)", "2026-07-06", "2026-11-20", "2026-10-23"),
]

TEACHERS = [
    ("T01", "Dr. Ananya Rao"), ("T02", "Prof. Vikram Menon"), ("T03", "Dr. Kavitha Iyer"),
    ("T04", "Prof. Rahul Deshpande"), ("T05", "Dr. Meera Krishnan"), ("T06", "Prof. Arjun Nair"),
]

SUBJECTS = [
    ("CS301", "Data Structures", 4, "SEM3", "T01", (0, 3)),
    ("CS302", "Discrete Mathematics", 3, "SEM3", "T05", (1, 4)),
    ("CS303", "Digital Logic Design", 3, "SEM3", "T03", (0, 2)),
    ("CS304", "Object Oriented Programming", 4, "SEM3", "T02", (1, 3)),
    ("HS301", "Professional Communication", 2, "SEM3", "T06", (2, 4)),
    ("CS401", "Database Management Systems", 4, "SEM4", "T01", (0, 2)),
    ("CS402", "Operating Systems", 4, "SEM4", "T02", (1, 3)),
    ("CS403", "Design and Analysis of Algorithms", 4, "SEM4", "T03", (0, 3)),
    ("CS404", "Computer Networks", 3, "SEM4", "T04", (2, 4)),
    ("MA401", "Probability and Statistics", 3, "SEM4", "T05", (1, 4)),
    ("CS405", "Software Engineering", 3, "SEM4", "T06", (0, 4)),
]

STUDENTS = [
    "Aarav Sharma", "Priya Nair", "Rohan Gupta", "Sneha Reddy", "Karthik Subramanian",
    "Divya Menon", "Aditya Kulkarni", "Ishita Verma", "Manoj Pillai", "Pooja Joshi",
    "Siddharth Rao", "Neha Kapoor", "Varun Bhat", "Ananya Das", "Rahul Mehta",
    "Lakshmi Iyer", "Farhan Ali", "Meghana Shetty",
]

HOLIDAYS = {"2026-01-26", "2026-03-04", "2026-03-20", "2026-08-15", "2026-08-27", "2026-10-02", "2026-10-20"}
LOW_ATTENDANCE = {"S105": 0.66, "S111": 0.70, "S116": 0.62}
WEAK_SUBJECT = {("S108", "CS402"): 0.60, ("S103", "CS301"): 0.64, ("S113", "MA401"): 0.66}
ASSESSMENTS = {"SEM3": [("internal", 20), ("midterm", 30), ("final", 50)],
               "SEM4": [("internal", 20), ("midterm", 30)]}


def class_dates(start, end, weekdays):
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    while day <= last:
        if day.weekday() in weekdays and day.isoformat() not in HOLIDAYS:
            yield day.isoformat()
        day += timedelta(days=1)


def generate_csvs(data_dir=DATA_DIR, seed=42):
    rng = random.Random(seed)
    data_dir.mkdir(parents=True, exist_ok=True)
    sem_attendance_end = {s[0]: (s[2], s[4]) for s in SEMESTERS}

    students = [(f"S{101 + i}", name) for i, name in enumerate(STUDENTS)]
    base_rate = {sid: LOW_ATTENDANCE.get(sid, rng.uniform(0.82, 0.96)) for sid, _ in students}
    ability = {sid: rng.uniform(0.45, 0.92) for sid, _ in students}

    attendance, marks = [], []
    for code, _, _, sem, _, weekdays in SUBJECTS:
        dates = list(class_dates(*sem_attendance_end[sem], weekdays))
        for sid, _ in students:
            rate = WEAK_SUBJECT.get((sid, code), base_rate[sid])
            rate = min(0.99, max(0.4, rate + rng.uniform(-0.04, 0.04)))
            present = 0
            for d in dates:
                is_present = rng.random() < rate
                present += is_present
                attendance.append((sid, code, d, "present" if is_present else "absent"))
            att_factor = present / len(dates)
            for kind, max_marks in ASSESSMENTS[sem]:
                score = 0.75 * ability[sid] + 0.25 * att_factor + rng.uniform(-0.08, 0.08)
                obtained = round(min(1.0, max(0.15, score)) * max_marks * 2) / 2
                marks.append((sid, code, kind, max_marks, obtained))

    frames = {
        "semesters": pd.DataFrame([s[:4] for s in SEMESTERS],
                                  columns=["semester_id", "name", "start_date", "end_date"]),
        "teachers": pd.DataFrame(
            [(tid, name, name.split()[-1].lower() + "." + tid.lower() + "@example.edu") for tid, name in TEACHERS],
            columns=["teacher_id", "name", "email"]),
        "students": pd.DataFrame(
            [(sid, name, sid.lower() + "@example.edu", "B.Tech CSE") for sid, name in students],
            columns=["student_id", "name", "email", "program"]),
        "subjects": pd.DataFrame([s[:5] for s in SUBJECTS],
                                 columns=["subject_code", "name", "credits", "semester_id", "teacher_id"]),
        "attendance": pd.DataFrame(attendance, columns=["student_id", "subject_code", "date", "status"]),
        "marks": pd.DataFrame(marks, columns=["student_id", "subject_code", "assessment_type",
                                              "max_marks", "obtained"]),
    }
    for kind, df in frames.items():
        df.to_csv(data_dir / f"{kind}.csv", index=False)
    return {kind: len(df) for kind, df in frames.items()}


def seed(db_path=None, data_dir=DATA_DIR):
    conn = get_connection(db_path)
    reset_db(conn)
    all_errors = []
    for kind in IMPORT_ORDER:
        imported, errors = import_csv(conn, kind, data_dir / f"{kind}.csv")
        print(f"{kind:<11} imported {imported:>5} rows, {len(errors)} errors")
        all_errors += errors
    print("DB counts:", table_counts(conn))
    conn.close()
    return all_errors


def main():
    parser = argparse.ArgumentParser(description="Reset the DB and load sample CSVs from data/.")
    parser.add_argument("--regenerate", action="store_true", help="rebuild the sample CSVs first")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: attendance.db)")
    args = parser.parse_args()
    if args.regenerate or not all((DATA_DIR / f"{k}.csv").exists() for k in IMPORT_ORDER):
        print("Generated CSVs:", generate_csvs())
    errors = seed(args.db)
    for err in errors[:20]:
        print("  " + err)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
