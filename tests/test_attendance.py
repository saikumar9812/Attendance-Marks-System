import pandas as pd
import pytest

import db
from importer import import_dataframe


def test_threshold_is_single_constant_of_75():
    assert db.ATTENDANCE_THRESHOLD == 75.0


@pytest.mark.parametrize("present,total,expected", [
    (30, 30, 100.0), (0, 30, 0.0), (15, 20, 75.0), (2, 3, 66.67), (29, 40, 72.5),
])
def test_attendance_pct(present, total, expected):
    assert db.attendance_pct(present, total) == expected


def test_attendance_pct_no_classes_is_none():
    assert db.attendance_pct(0, 0) is None


@pytest.mark.parametrize("pct,expected", [
    (74.99, True), (0.0, True), (75.0, False), (75.01, False), (100.0, False),
    (None, False), (float("nan"), False),
])
def test_below_threshold_flag(pct, expected):
    assert db.is_below_threshold(pct) is expected


def test_flag_respects_custom_threshold():
    assert db.is_below_threshold(79.0, threshold=80) is True
    assert db.is_below_threshold(80.0, threshold=80) is False


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test.db")
    db.init_db(connection)
    import_dataframe(connection, "semesters", pd.DataFrame(
        [{"semester_id": "S1", "name": "Sem 1", "start_date": "2026-01-01", "end_date": "2026-05-01"}]))
    import_dataframe(connection, "teachers", pd.DataFrame([{"teacher_id": "T1", "name": "Teacher"}]))
    import_dataframe(connection, "students", pd.DataFrame(
        [{"student_id": "A", "name": "Alice"}, {"student_id": "B", "name": "Bob"}]))
    import_dataframe(connection, "subjects", pd.DataFrame([
        {"subject_code": "X1", "name": "Sub X", "credits": "3", "semester_id": "S1", "teacher_id": "T1"},
        {"subject_code": "Y1", "name": "Sub Y", "credits": "4", "semester_id": "S1", "teacher_id": "T1"},
    ]))
    rows = []
    for subject, a_present, b_present in [("X1", 8, 7), ("Y1", 10, 9)]:
        for day in range(10):
            date = f"2026-02-{day + 1:02d}"
            rows.append({"student_id": "A", "subject_code": subject, "date": date,
                         "status": "present" if day < a_present else "absent"})
            rows.append({"student_id": "B", "subject_code": subject, "date": date,
                         "status": "present" if day < b_present else "absent"})
    imported, errors = import_dataframe(connection, "attendance", pd.DataFrame(rows))
    assert (imported, errors) == (40, [])
    yield connection
    connection.close()


def test_per_subject_and_overall_flags_from_db(conn):
    summary = db.subject_summary(conn).set_index(["student_id", "subject_code"])
    assert summary.loc[("A", "X1"), "attendance_pct"] == 80.0
    assert summary.loc[("B", "X1"), "attendance_pct"] == 70.0
    assert not summary.loc[("A", "X1"), "below_threshold"]
    assert summary.loc[("B", "X1"), "below_threshold"]
    assert not summary.loc[("B", "Y1"), "below_threshold"]

    overall = db.overall_summary(db.subject_summary(conn)).set_index("student_id")
    assert overall.loc["A", "overall_attendance_pct"] == 90.0
    assert overall.loc["B", "overall_attendance_pct"] == 80.0
    assert not overall.loc["B", "below_threshold"]


def test_overall_is_weighted_by_classes_not_average_of_percentages(conn):
    extra = [{"student_id": "B", "subject_code": "X1", "date": f"2026-03-{d:02d}", "status": "absent"}
             for d in range(1, 21)]
    import_dataframe(conn, "attendance", pd.DataFrame(extra))
    overall = db.overall_summary(db.subject_summary(conn)).set_index("student_id")
    assert overall.loc["B", "overall_attendance_pct"] == db.attendance_pct(16, 40)
    assert overall.loc["B", "below_threshold"]


def test_invalid_attendance_status_is_rejected(conn):
    imported, errors = import_dataframe(conn, "attendance", pd.DataFrame(
        [{"student_id": "A", "subject_code": "X1", "date": "2026-04-01", "status": "late"}]))
    assert imported == 0 and "invalid status" in errors[0]
