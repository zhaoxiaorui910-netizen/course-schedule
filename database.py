import sqlite3
import os
from datetime import date, datetime

_db_name = "test.db" if os.environ.get("COURSE_SCHEDULE_TEST") else "schedule.db"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), _db_name)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS semester (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            start_date  TEXT NOT NULL,
            end_date    TEXT NOT NULL,
            weeks       INTEGER NOT NULL DEFAULT 20,
            is_current  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS course (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            semester_id     INTEGER NOT NULL,
            name            TEXT NOT NULL,
            teacher         TEXT DEFAULT '',
            location        TEXT DEFAULT '',
            day_of_week     INTEGER NOT NULL,
            start_period    INTEGER NOT NULL,
            end_period      INTEGER NOT NULL,
            start_week      INTEGER NOT NULL DEFAULT 1,
            end_week        INTEGER NOT NULL DEFAULT 20,
            week_type       TEXT DEFAULT '',
            color           TEXT DEFAULT '',
            source          TEXT DEFAULT 'manual',
            FOREIGN KEY (semester_id) REFERENCES semester(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


# ---- 学期操作 ----

def create_semester(name: str, start_date: str, end_date: str,
                    weeks: int = 20, is_current: bool = False) -> int:
    conn = get_conn()
    if is_current:
        conn.execute("UPDATE semester SET is_current = 0")
    conn.execute(
        "INSERT INTO semester (name, start_date, end_date, weeks, is_current) VALUES (?, ?, ?, ?, ?)",
        (name, start_date, end_date, weeks, int(is_current)),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return int(rid)


def get_semesters() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM semester ORDER BY start_date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_semester(semester_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM semester WHERE id = ?", (semester_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_current_semester() -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM semester WHERE is_current = 1").fetchone()
    conn.close()
    if row:
        return dict(row)
    # fallback: 取最新的学期
    semesters = get_semesters()
    return semesters[0] if semesters else None


def update_semester(semester_id: int, **kwargs) -> bool:
    conn = get_conn()
    if kwargs.get("is_current"):
        conn.execute("UPDATE semester SET is_current = 0")
    fields = []
    values = []
    for k, v in kwargs.items():
        if v is not None:
            fields.append(f"{k} = ?")
            values.append(v)
    if not fields:
        conn.close()
        return False
    values.append(semester_id)
    conn.execute(f"UPDATE semester SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


def delete_semester(semester_id: int) -> bool:
    conn = get_conn()
    conn.execute("DELETE FROM semester WHERE id = ?", (semester_id,))
    conn.commit()
    conn.close()
    return True


# ---- 课程操作 ----

def create_course(semester_id: int, name: str, day_of_week: int,
                  start_period: int, end_period: int,
                  teacher: str = "", location: str = "",
                  start_week: int = 1, end_week: int = 20,
                  week_type: str = "", color: str = "",
                  source: str = "manual") -> int:
    conn = get_conn()
    conn.execute(
        """INSERT INTO course
           (semester_id, name, teacher, location, day_of_week,
            start_period, end_period, start_week, end_week, week_type, color, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (semester_id, name, teacher, location, day_of_week,
         start_period, end_period, start_week, end_week, week_type, color, source),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return int(rid)


def get_courses(semester_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM course WHERE semester_id = ? ORDER BY day_of_week, start_period",
        (semester_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_course(course_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM course WHERE id = ?", (course_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_course(course_id: int, **kwargs) -> bool:
    conn = get_conn()
    fields = []
    values = []
    for k, v in kwargs.items():
        if v is not None:
            fields.append(f"{k} = ?")
            values.append(v)
    if not fields:
        conn.close()
        return False
    values.append(course_id)
    conn.execute(f"UPDATE course SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


def delete_course(course_id: int) -> bool:
    conn = get_conn()
    conn.execute("DELETE FROM course WHERE id = ?", (course_id,))
    conn.commit()
    conn.close()
    return True


def delete_courses_by_semester(semester_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM course WHERE semester_id = ?", (semester_id,))
    conn.commit()
    conn.close()


def import_courses(semester_id: int, courses: list[dict]):
    """批量导入课程（先清空该学期非手动课程，再插入）"""
    conn = get_conn()
    conn.execute("DELETE FROM course WHERE semester_id = ? AND source IN ('scraper', 'mock')", (semester_id,))
    for c in courses:
        conn.execute(
            """INSERT INTO course
               (semester_id, name, teacher, location, day_of_week,
                start_period, end_period, start_week, end_week, week_type, color, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (semester_id, c["name"], c.get("teacher", ""), c.get("location", ""),
             c["day_of_week"], c["start_period"], c["end_period"],
             c.get("start_week", 1), c.get("end_week", 20),
             c.get("week_type", ""), c.get("color", ""), "scraper"),
        )
    conn.commit()
    conn.close()
