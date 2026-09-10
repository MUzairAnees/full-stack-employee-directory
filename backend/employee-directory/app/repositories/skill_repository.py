"""Data access for skills — the shared lookup list, and the per-employee
employee_skills join table.
"""

import psycopg
from psycopg.rows import class_row

from app.models.skill import Skill
from app.repositories.db import get_connection

_COLUMNS = "id, name"


def list_skills() -> list[Skill]:
    """Returns every skill, ordered by name — the full lookup list."""
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Skill)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM skills ORDER BY name")
        return cur.fetchall()


def list_employee_skills(employee_id: int) -> list[Skill]:
    """Returns the skills attached to this employee, ordered by name."""
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Skill)) as cur:
        cur.execute(
            """
            SELECT s.id, s.name
            FROM skills s
            JOIN employee_skills es ON es.skill_id = s.id
            WHERE es.employee_id = %s
            ORDER BY s.name
            """,
            (employee_id,),
        )
        return cur.fetchall()


def _find_skill_by_lower_name(conn, lower_name: str) -> Skill | None:
    with conn.cursor(row_factory=class_row(Skill)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM skills WHERE LOWER(name) = %s", (lower_name,))
        return cur.fetchone()


def get_or_create_skill(name: str) -> Skill:
    """Finds a skill by case-insensitive name, or creates it.

    Handles the concurrent-insert race explicitly: two containers adding
    "Python" at the same instant can both miss the initial SELECT and
    both attempt the INSERT — one succeeds, the other hits
    idx_skills_name_lower's UniqueViolation. Caught here, then re-SELECT
    to attach to whatever row is there now. The caller never sees an
    error for this — it's expected concurrent behaviour on Lambda, not
    an edge case.

    Known, accepted limitation (see README): "JavaScript" and "JS" are
    different rows and are never merged automatically — only exact
    case-insensitive matches reuse a row.
    """
    conn = get_connection()
    lower_name = name.lower()

    skill = _find_skill_by_lower_name(conn, lower_name)
    if skill is not None:
        return skill

    try:
        with conn.cursor(row_factory=class_row(Skill)) as cur:
            cur.execute(f"INSERT INTO skills (name) VALUES (%s) RETURNING {_COLUMNS}", (name,))
            return cur.fetchone()
    except psycopg.errors.UniqueViolation as err:
        conn.rollback()
        skill = _find_skill_by_lower_name(conn, lower_name)
        assert skill is not None, "UniqueViolation on insert but the re-SELECT found nothing"
        return skill


def attach_skill(employee_id: int, skill_id: int) -> bool:
    """Links a skill to an employee. Idempotent via ON CONFLICT DO
    NOTHING on the (employee_id, skill_id) composite primary key — no
    separate existence check needed; attaching a skill the employee
    already has is a true no-op at the database level.

    Returns:
        bool: True if a NEW employee_skills row was created, False if
        the employee already had this skill. The caller (skill_service)
        uses this to choose 201 vs 200 — regardless of whether the skill
        lookup row itself was also newly created.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO employee_skills (employee_id, skill_id) VALUES (%s, %s) "
            "ON CONFLICT (employee_id, skill_id) DO NOTHING",
            (employee_id, skill_id),
        )
        return cur.rowcount > 0


def detach_skill(employee_id: int, skill_id: int) -> None:
    """Unlinks a skill from an employee. Idempotent by nature — deleting
    a row that isn't there affects 0 rows, not an error. There's no
    entity to report "not found" for here: employee_skills is a join
    row, not something with its own identity to look up.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM employee_skills WHERE employee_id = %s AND skill_id = %s", (employee_id, skill_id))
