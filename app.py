import altair as alt
import pandas as pd
import streamlit as st

import db
from importer import IMPORT_ORDER, REQUIRED_COLUMNS, import_csv

THRESHOLD = db.ATTENDANCE_THRESHOLD
FLAG_TEXT = f"BELOW {THRESHOLD:g}%"
RED, GREEN = "#d62728", "#2ca02c"

st.set_page_config(page_title="Attendance & Marks", layout="wide")


def fmt_pct(value):
    return "-" if value is None or pd.isna(value) else f"{value:.1f}%"


def semester_picker(conn, key, label="Semester"):
    sems = db.list_semesters(conn)
    options = [None] + sems["semester_id"].tolist()
    names = dict(zip(sems["semester_id"], sems["name"]))
    return st.selectbox(label, options, index=len(options) - 1 if len(options) > 1 else 0,
                        format_func=lambda s: "All semesters" if s is None else names[s], key=key)


def highlight_low(value):
    return f"background-color: {RED}33; color: {RED}; font-weight: 600" if db.is_below_threshold(value) else ""


def attendance_chart(df, label_col):
    data = df.assign(status=df["below_threshold"].map({True: FLAG_TEXT, False: "OK"}))
    bars = alt.Chart(data).mark_bar().encode(
        x=alt.X(f"{label_col}:N", sort=None, title=None),
        y=alt.Y("attendance_pct:Q", title="Attendance %", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("status:N", scale=alt.Scale(domain=["OK", FLAG_TEXT], range=[GREEN, RED]), title=None),
        tooltip=[label_col, alt.Tooltip("attendance_pct:Q", format=".1f"), "present", "total_classes"],
    )
    rule = alt.Chart(pd.DataFrame({"y": [THRESHOLD]})).mark_rule(strokeDash=[6, 4], color=RED).encode(y="y:Q")
    return (bars + rule).properties(height=320)


def login_sidebar(conn):
    st.sidebar.title("Attendance & Marks")
    user = st.session_state.get("user")
    if user:
        st.sidebar.success(f"Logged in as {user['name']} ({user['role']})")
        if st.sidebar.button("Log out"):
            st.session_state.pop("user")
            st.rerun()
        return user

    role = st.sidebar.radio("Role", ["student", "teacher"], format_func=str.title, horizontal=True)
    people = db.list_students(conn) if role == "student" else db.list_teachers(conn)
    id_col = f"{role}_id"
    if people.empty:
        st.sidebar.warning("No users in the database. Run `python seed.py` first.")
        return None
    names = dict(zip(people[id_col], people["name"]))
    user_id = st.sidebar.selectbox("User", people[id_col].tolist(), format_func=lambda i: f"{i} - {names[i]}")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Log in", type="primary"):
        if db.verify_login(conn, role, user_id, password):
            st.session_state["user"] = {"role": role, "id": user_id, "name": names[user_id]}
            st.rerun()
        st.sidebar.error("Invalid password.")
    st.sidebar.caption(f"Seeded demo password for every user: `{db.DEFAULT_PASSWORD}`")
    return None


def student_dashboard(conn, user):
    st.title(f"Welcome, {user['name']}")
    st.caption(f"Student ID {user['id']} | Minimum required attendance: {THRESHOLD:g}%")
    semester_id = semester_picker(conn, "student_sem")

    summary = db.subject_summary(conn, student_id=user["id"], semester_id=semester_id)
    if summary.empty:
        st.info("No attendance or marks recorded for this selection.")
        return
    overall = db.overall_summary(summary).iloc[0]
    low_subjects = summary[summary["below_threshold"]]

    if overall["below_threshold"]:
        st.error(f"Overall attendance is {fmt_pct(overall['overall_attendance_pct'])}, "
                 f"below the required {THRESHOLD:g}%.")
    if not low_subjects.empty:
        st.warning("Attendance below " + f"{THRESHOLD:g}% in: " + ", ".join(
            f"{r.subject_code} {r.subject_name} ({fmt_pct(r.attendance_pct)})" for r in low_subjects.itertuples()))
    if not overall["below_threshold"] and low_subjects.empty:
        st.success(f"Attendance is at or above {THRESHOLD:g}% overall and in every subject.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Overall attendance", fmt_pct(overall["overall_attendance_pct"]),
              f"{overall['present']}/{overall['total_classes']} classes", delta_color="off")
    c2.metric("Overall marks", fmt_pct(overall["overall_marks_pct"]),
              f"{overall['marks_obtained']:g}/{overall['marks_max']:g}", delta_color="off")
    c3.metric("Subjects", len(summary))
    c4.metric(f"Subjects below {THRESHOLD:g}%", len(low_subjects))

    table = summary.assign(
        status=summary["below_threshold"].map({True: FLAG_TEXT, False: "OK"}),
        classes=summary["present"].astype(str) + "/" + summary["total_classes"].astype(str),
    )[["subject_code", "subject_name", "semester", "credits", "classes", "attendance_pct", "marks_obtained",
       "marks_max", "marks_pct", "status"]]
    st.subheader("Per-subject summary")
    st.dataframe(table.style.map(highlight_low, subset=["attendance_pct"])
                 .format({"attendance_pct": fmt_pct, "marks_pct": fmt_pct, "marks_obtained": "{:g}",
                          "marks_max": "{:g}"}, na_rep="-"), hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Attendance by subject")
        st.altair_chart(attendance_chart(summary, "subject_code"), width="stretch")
    with right:
        st.subheader("Marks by assessment")
        marks = db.student_marks(conn, user["id"], semester_id)
        if marks.empty:
            st.info("No marks recorded.")
        else:
            chart = alt.Chart(marks).mark_bar().encode(
                x=alt.X("subject_code:N", title=None),
                xOffset=alt.XOffset("assessment_type:N", sort=db.ASSESSMENT_ORDER),
                y=alt.Y("pct:Q", title="Score %", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("assessment_type:N", sort=db.ASSESSMENT_ORDER, title="Assessment"),
                tooltip=["subject_name", "assessment_type", "obtained", "max_marks", "pct"],
            ).properties(height=320)
            st.altair_chart(chart, width="stretch")

    st.subheader("Marks detail")
    st.dataframe(marks, hide_index=True)

    with st.expander("Attendance log for a subject"):
        code = st.selectbox("Subject", summary["subject_code"].tolist(),
                            format_func=lambda c: f"{c} - {summary.set_index('subject_code').at[c, 'subject_name']}")
        st.dataframe(db.student_attendance_log(conn, user["id"], code), hide_index=True)


def build_class_matrix(summary, overall):
    att = summary.pivot(index="student_id", columns="subject_code", values="attendance_pct")
    mk = summary.pivot(index="student_id", columns="subject_code", values="marks_pct")
    att.columns = [f"{c} Att %" for c in att.columns]
    mk.columns = [f"{c} Marks %" for c in mk.columns]
    ordered = [col for code in summary["subject_code"].unique() for col in (f"{code} Att %", f"{code} Marks %")]
    matrix = att.join(mk)[ordered].reset_index()
    over = overall[["student_id", "student_name", "overall_attendance_pct", "overall_marks_pct", "below_threshold"]]
    matrix = over.merge(matrix, on="student_id").rename(columns={
        "student_name": "Student", "overall_attendance_pct": "Overall Att %", "overall_marks_pct": "Overall Marks %"})
    matrix["Flag"] = [
        FLAG_TEXT if overall_low else (f"Low in {', '.join(c.split()[0] for c in low)}" if low else "")
        for overall_low, low in zip(
            matrix["below_threshold"],
            matrix[[c for c in matrix.columns if c.endswith("Att %") and c != "Overall Att %"]].apply(
                lambda r: [c for c, v in r.items() if db.is_below_threshold(v)], axis=1))
    ]
    return matrix.drop(columns="below_threshold").rename(columns={"student_id": "Student ID"})


def class_view(conn, user):
    f1, f2, f3 = st.columns([2, 1, 3])
    with f1:
        semester_id = semester_picker(conn, "teacher_sem")
    with f2:
        mine_only = st.checkbox("Only my subjects", value=False)
    subjects = db.list_subjects(conn, semester_id)
    if mine_only:
        subjects = subjects[subjects["teacher_id"] == user["id"]]
    labels = dict(zip(subjects["subject_code"], subjects["name"]))
    with f3:
        chosen = st.multiselect("Subjects", subjects["subject_code"].tolist(),
                                format_func=lambda c: f"{c} - {labels[c]}", placeholder="All subjects")
    codes = chosen or subjects["subject_code"].tolist()

    summary = db.subject_summary(conn, semester_id=semester_id)
    summary = summary[summary["subject_code"].isin(codes)]
    if summary.empty:
        st.info("No data for this selection.")
        return
    overall = db.overall_summary(summary)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Students", overall["student_id"].nunique())
    c2.metric("Class avg attendance", fmt_pct(overall["overall_attendance_pct"].mean()))
    c3.metric("Class avg marks", fmt_pct(overall["overall_marks_pct"].mean()))
    c4.metric(f"Students below {THRESHOLD:g}% overall", int(overall["below_threshold"].sum()))

    st.subheader("Combined class view (students x subjects)")
    st.caption(f"Cells in red are below {THRESHOLD:g}% attendance. Overall columns cover the filtered subjects.")
    matrix = build_class_matrix(summary, overall)
    att_cols = [c for c in matrix.columns if c.endswith("Att %")]
    pct_cols = att_cols + [c for c in matrix.columns if c.endswith("Marks %")]
    st.dataframe(matrix.style.map(highlight_low, subset=att_cols)
                 .format({c: fmt_pct for c in pct_cols}, na_rep="-"), hide_index=True)
    st.download_button("Export class view (CSV)", matrix.to_csv(index=False).encode("utf-8"),
                       file_name="class_view.csv", mime="text/csv")

    st.subheader("Class averages by subject")
    averages = summary.groupby(["subject_code", "subject_name"], as_index=False, sort=False).agg(
        avg_attendance_pct=("attendance_pct", "mean"),
        avg_marks_pct=("marks_pct", "mean"),
        students_below=("below_threshold", "sum"),
    ).round(2)
    left, right = st.columns([3, 2])
    with left:
        st.dataframe(averages.style.map(highlight_low, subset=["avg_attendance_pct"])
                     .format({"avg_attendance_pct": fmt_pct, "avg_marks_pct": fmt_pct}), hide_index=True)
    with right:
        chart_df = averages.rename(columns={"avg_attendance_pct": "attendance_pct"}).assign(
            below_threshold=lambda d: d["attendance_pct"].apply(db.is_below_threshold), present="-",
            total_classes="-")
        st.altair_chart(attendance_chart(chart_df, "subject_code"), width="stretch")

    st.subheader(f"Flagged: attendance below {THRESHOLD:g}%")
    flagged = summary[summary["below_threshold"]][
        ["student_id", "student_name", "subject_code", "subject_name", "present", "total_classes", "attendance_pct"]]
    if flagged.empty:
        st.success("No student is below the threshold for the selected subjects.")
    else:
        st.dataframe(flagged.style.format({"attendance_pct": fmt_pct}), hide_index=True)
        st.download_button("Export flagged list (CSV)", flagged.to_csv(index=False).encode("utf-8"),
                           file_name="below_threshold.csv", mime="text/csv")

    with st.expander("Detailed records (assessment breakdown)"):
        marks = db.class_marks(conn, semester_id)
        breakdown = marks.pivot_table(index=["student_id", "subject_code"], columns="assessment_type",
                                      values="obtained", aggfunc="sum").reset_index()
        breakdown.columns.name = None
        detail = summary.merge(breakdown, on=["student_id", "subject_code"], how="left")
        detail_cols = ["student_id", "student_name", "subject_code", "subject_name", "semester", "present",
                       "total_classes", "attendance_pct"] + [a for a in db.ASSESSMENT_ORDER if a in detail.columns] \
            + ["marks_obtained", "marks_max", "marks_pct", "below_threshold"]
        detail = detail[detail_cols]
        st.dataframe(detail, hide_index=True)
        st.download_button("Export detailed records (CSV)", detail.to_csv(index=False).encode("utf-8"),
                           file_name="detailed_records.csv", mime="text/csv")


def import_view(conn):
    st.subheader("Import data from CSV")
    st.caption("Rows are upserted (existing keys are updated). Import in this order so references resolve: "
               + " -> ".join(IMPORT_ORDER))
    kind = st.selectbox("Data type", IMPORT_ORDER)
    st.markdown("Required columns: " + ", ".join(f"`{c}`" for c in REQUIRED_COLUMNS[kind]))
    upload = st.file_uploader("CSV file", type=["csv"], key=f"upload_{kind}")
    if upload is None:
        return
    preview = pd.read_csv(upload, dtype=str, keep_default_na=False)
    st.dataframe(preview.head(20), hide_index=True)
    st.caption(f"{len(preview)} rows in file")
    if st.button("Import", type="primary"):
        upload.seek(0)
        imported, errors = import_csv(conn, kind, upload)
        st.success(f"Imported {imported} {kind} rows.")
        if errors:
            st.error(f"{len(errors)} rows skipped:\n\n" + "\n".join(f"- {e}" for e in errors[:50]))
        st.write(db.table_counts(conn))


def teacher_view(conn, user):
    st.title(f"Teacher dashboard - {user['name']}")
    mine = db.list_subjects(conn)
    mine = mine[mine["teacher_id"] == user["id"]]
    st.caption("Your subjects: " + (", ".join(f"{r.subject_code} {r.name}" for r in mine.itertuples()) or "none"))
    tab_class, tab_import = st.tabs(["Class view", "Import CSV"])
    with tab_class:
        class_view(conn, user)
    with tab_import:
        import_view(conn)


def landing(conn):
    st.title("Attendance & Marks System")
    st.write("Log in from the sidebar as a **student** to see your attendance and marks, or as a **teacher** "
             "for the combined class view, exports and CSV import.")
    st.info(f"Students below {THRESHOLD:g}% attendance (overall or per subject) are flagged.")
    st.write("Database contents:", db.table_counts(conn))


def main():
    conn = db.get_connection()
    try:
        db.init_db(conn)
        user = login_sidebar(conn)
        if user is None:
            landing(conn)
        elif user["role"] == "student":
            student_dashboard(conn, user)
        else:
            teacher_view(conn, user)
    finally:
        conn.close()


main()
