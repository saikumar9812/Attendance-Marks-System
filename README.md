# Attendance & Marks System

A small Python + SQLite + Streamlit app that pulls attendance, marks and semester subject details into one system, with a student dashboard, a teacher class view, CSV import/export, and a single 75% attendance threshold that drives every warning flag.

For a full walkthrough (architecture, schema diagrams, calculations, every view, troubleshooting), see [IMPLEMENTATION.md](IMPLEMENTATION.md).

## Features

- **One database** (SQLite, `attendance.db`) for semesters, teachers, students, subjects, attendance and marks.
- **CSV import**: the `importer.py` CLI and an upload tab in the teacher UI. Rows are validated and upserted, and bad rows are reported by line number.
- **Sample data**: 18 students, 6 teachers, 2 semesters, 11 subjects (5 + 6), 6,246 attendance rows and 486 marks rows. Three students are below 75% overall, and several more are below 75% in individual subjects.
- **Simple login**: choose Student or Teacher, pick a user from the list and enter the seeded password (`pass123`).
- **Student dashboard**: attendance % per subject and overall, marks per subject and assessment, overall marks %, charts, and red/amber warnings when attendance is below 75% (overall and per subject).
- **Teacher class view**: a students × subjects matrix of attendance % and marks %, class averages, filters (semester, my subjects, subject list), highlighting and a Flag column for students below 75%, and CSV export (matrix, flagged list, detailed records).
- **One threshold constant**: `ATTENDANCE_THRESHOLD = 75.0` in `db.py`.
- **pytest tests** for the attendance % calculation and the below-75% flag logic.

## Schema (summary)

| Table | Key columns |
|---|---|
| `semesters` | `semester_id` PK, `name`, `start_date`, `end_date` |
| `teachers` | `teacher_id` PK, `name`, `email`, `password_hash` |
| `students` | `student_id` PK, `name`, `email`, `program`, `password_hash` |
| `subjects` | `subject_code` PK, `name`, `credits`, `semester_id` FK, `teacher_id` FK |
| `attendance` | `id` PK, `student_id` FK, `subject_code` FK, `date`, `status` (`present`/`absent`), UNIQUE(student, subject, date) |
| `marks` | `id` PK, `student_id` FK, `subject_code` FK, `assessment_type`, `max_marks`, `obtained`, UNIQUE(student, subject, assessment) |

## Setup

Windows (PowerShell):

```powershell
cd attendance-marks-system
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux / macOS:

```bash
cd attendance-marks-system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python seed.py                 # (re)create attendance.db from data/*.csv
streamlit run app.py           # open http://localhost:8501
pytest                         # run tests
```

- `python seed.py --regenerate` rebuilds the sample CSVs with a fixed random seed, so the output is the same each time, then reseeds.
- `python importer.py attendance path/to/file.csv` imports one CSV. The types are `semesters`, `teachers`, `students`, `subjects`, `attendance` and `marks`. Import them in that order.
- Set the `AMS_DB_PATH` environment variable to use a different database file.

## Demo logins

| Role | Users | Password |
|---|---|---|
| Student | `S101` to `S118` (flagged examples: `S105`, `S108`, `S116`; `S111` is fine overall but low in some subjects) | `pass123` |
| Teacher | `T01` to `T06` | `pass123` |

## Project layout

```
app.py            Streamlit UI (login, student dashboard, teacher view, CSV upload)
db.py             Schema, threshold constant, calculations, queries
importer.py       CSV validation/upsert + CLI
seed.py           Sample-data generator + DB reset/seed
data/*.csv        Sample CSVs (semesters, teachers, students, subjects, attendance, marks)
tests/            pytest tests
```
