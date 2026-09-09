"""Data access for departments."""

import psycopg
from psycopg.rows import class_row

from app.exceptions import DependentsExistError, DuplicateError, NotFoundError
from app.models.department import Department
from app.repositories.db import get_connection

_COLUMNS = "id, name, is_active, created_at, updated_at"


def list_departments(*, include_inactive: bool = False) -> list[Department]:
    """Returns departments, ordered by name.

    Args:
        include_inactive: If False (default), soft-deleted departments
            are excluded.

    Returns:
        list[Department]: The matching rows — possibly empty, never an
        error just because nothing matched.
    """
    conn = get_connection()
    where = "" if include_inactive else "WHERE is_active"
    with conn.cursor(row_factory=class_row(Department)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM departments {where} ORDER BY name")
        return cur.fetchall()


def get_department(department_id: int) -> Department:
    """Returns a department by id — active or not. A direct id request
    is explicit; hiding inactive rows here (as the list endpoint does by
    default) would make a soft-deleted department unrecoverable, since
    nobody could ever look it up to restore it.

    Raises:
        NotFoundError: If no department has that id at all.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Department)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM departments WHERE id = %s", (department_id,))
        department = cur.fetchone()
        if department is None:
            raise NotFoundError(f"department {department_id} not found")
        return department


def create_department(name: str) -> Department:
    """Raises:
    DuplicateError: If the name collides with an existing department —
        active or soft-deleted; soft delete keeps the name, so this is
        the common case, not an edge case.
    """
    conn = get_connection()
    try:
        with conn.cursor(row_factory=class_row(Department)) as cur:
            cur.execute(
                f"INSERT INTO departments (name) VALUES (%s) RETURNING {_COLUMNS}",
                (name,),
            )
            return cur.fetchone()
    except psycopg.errors.UniqueViolation as err:
        conn.rollback()
        raise DuplicateError(f"a department named '{name}' already exists") from err


def update_department(department_id: int, name: str | None, is_active: bool | None) -> Department:
    """Updates name and/or is_active. is_active is only ever True here —
    app/schemas/department.py's validation rejects False before this is
    ever reached (that's what DELETE is for).

    Raises:
        NotFoundError: If no department has that id.
        DuplicateError: If the new name collides with an existing one.
    """
    get_department(department_id)  # raises NotFoundError if no such row

    updates: list[str] = []
    params: list = []
    if name is not None:
        updates.append("name = %s")
        params.append(name)
    if is_active is not None:
        updates.append("is_active = %s")
        params.append(is_active)
    if not updates:
        return get_department(department_id)

    updates.append("updated_at = now()")
    params.append(department_id)

    conn = get_connection()
    try:
        with conn.cursor(row_factory=class_row(Department)) as cur:
            cur.execute(
                f"UPDATE departments SET {', '.join(updates)} WHERE id = %s RETURNING {_COLUMNS}",
                params,
            )
            return cur.fetchone()
    except psycopg.errors.UniqueViolation as err:
        conn.rollback()
        raise DuplicateError(f"a department named '{name}' already exists") from err


def _has_active_employees(department_id: int) -> bool:
    """Active employees through teams, not filtered on teams.is_active —
    deliberately: checking only active teams would depend on "every team
    has an active manager", an invariant that lives in slice 5 and
    doesn't exist yet. An active person sitting on an otherwise-
    deactivated team should still block deletion; this checks people,
    not teams, all the way through.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM teams t
                JOIN employees e ON e.team_id = t.id
                WHERE t.department_id = %s AND e.is_active
            )
            """,
            (department_id,),
        )
        return cur.fetchone()[0]


def soft_delete_department(department_id: int) -> Department:
    """Soft-deletes a department, or no-ops if it's already inactive.

    The already-inactive check runs BEFORE the active-employees guard,
    not after — deliberately. If the guard ran first, a department that
    was already deactivated could later fail with a 409 once slice 5
    exists and employees get reactivated onto its teams, which makes no
    sense for something already deleted: idempotent means idempotent
    regardless of what changes around it later.

    Raises:
        NotFoundError: If no department has that id.
        DependentsExistError: If it has any active employee, through
            teams, and isn't already inactive.
    """
    department = get_department(department_id)
    if not department.is_active:
        return department

    if _has_active_employees(department_id):
        raise DependentsExistError(f"department {department_id} has active employees and cannot be deleted")

    conn = get_connection()
    with conn.cursor(row_factory=class_row(Department)) as cur:
        cur.execute(
            f"UPDATE departments SET is_active = false, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
            (department_id,),
        )
        return cur.fetchone()
