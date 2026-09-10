"""Data access for projects — the shared lookup list, and the
per-employee employee_projects join (which carries completed_at, unlike
employee_skills' plain join).
"""

import psycopg
from psycopg.rows import class_row

from app.exceptions import DuplicateError, NotFoundError
from app.models.project import Project, ProjectAssignment
from app.repositories.db import get_connection

_COLUMNS = "id, name, description"

# Sentinel distinguishing "description not included in this update at
# all" (leave it alone) from "description included, and is null" (clear
# it) — same shape as employee_repository.UNSET, not imported from there:
# each repository module is self-contained, no cross-module sentinel
# sharing.
UNSET = object()


def list_projects() -> list[Project]:
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Project)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM projects ORDER BY name")
        return cur.fetchall()


def get_project(project_id: int) -> Project:
    """Raises:
    NotFoundError: no project has this id.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Project)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM projects WHERE id = %s", (project_id,))
        project = cur.fetchone()
        if project is None:
            raise NotFoundError(f"project {project_id} not found")
        return project


def _translate_unique_violation(name: str) -> DuplicateError:
    # Both projects_name_key (exact) and idx_projects_name_lower (case
    # variant) mean the same thing to the caller — "this name is taken"
    # — so unlike employee FK violations, there's no need to branch on
    # which constraint actually fired.
    return DuplicateError(f"a project named '{name}' already exists")


def create_project(name: str, description: str | None) -> Project:
    """Explicit create — open to any authenticated user (see
    project_service), but NOT get-or-create: 409s on a name collision,
    case-insensitive, rather than silently reusing the existing row.
    That's what keeps PUT /projects/{id}'s Admin gate meaningful — if
    POST instead merged into an existing row, anyone could route around
    the gate by re-POSTing a new description under the same name.

    Raises:
        DuplicateError: a project with this name (any case) exists.
    """
    conn = get_connection()
    try:
        with conn.cursor(row_factory=class_row(Project)) as cur:
            cur.execute(f"INSERT INTO projects (name, description) VALUES (%s, %s) RETURNING {_COLUMNS}", (name, description))
            return cur.fetchone()
    except psycopg.errors.UniqueViolation as err:
        conn.rollback()
        raise _translate_unique_violation(name) from err


def update_project(project_id: int, name: str | None = None, description=UNSET) -> Project:
    """Admin only (enforced by the controller). Same 409-on-collision as
    create — renaming to an existing name doesn't merge, it's rejected.

    Raises:
        NotFoundError: no project has this id.
        DuplicateError: the new name collides (any case) with another
            project.
    """
    get_project(project_id)  # raises NotFoundError if missing

    updates: list[str] = []
    params: list = []
    if name is not None:
        updates.append("name = %s")
        params.append(name)
    if description is not UNSET:
        updates.append("description = %s")
        params.append(description)
    if not updates:
        return get_project(project_id)

    params.append(project_id)
    conn = get_connection()
    try:
        with conn.cursor(row_factory=class_row(Project)) as cur:
            cur.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = %s RETURNING {_COLUMNS}", params)
            return cur.fetchone()
    except psycopg.errors.UniqueViolation as err:
        conn.rollback()
        raise _translate_unique_violation(name) from err


def _find_project_by_lower_name(conn, lower_name: str) -> Project | None:
    with conn.cursor(row_factory=class_row(Project)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM projects WHERE LOWER(name) = %s", (lower_name,))
        return cur.fetchone()


def get_or_create_project(name: str) -> Project:
    """Get-or-create by case-insensitive name — used ONLY by the attach
    path (POST /employees/{id}/projects), never sets description. Same
    concurrent-insert race handling as skill_repository.get_or_create_skill:
    catches the UniqueViolation from two containers racing to create the
    same project and re-SELECTs to attach to whatever's there now,
    rather than erroring.
    """
    conn = get_connection()
    lower_name = name.lower()

    project = _find_project_by_lower_name(conn, lower_name)
    if project is not None:
        return project

    try:
        with conn.cursor(row_factory=class_row(Project)) as cur:
            cur.execute(f"INSERT INTO projects (name, description) VALUES (%s, NULL) RETURNING {_COLUMNS}", (name,))
            return cur.fetchone()
    except psycopg.errors.UniqueViolation as err:
        conn.rollback()
        project = _find_project_by_lower_name(conn, lower_name)
        assert project is not None, "UniqueViolation on insert but the re-SELECT found nothing"
        return project


def list_employee_projects(employee_id: int) -> list[ProjectAssignment]:
    conn = get_connection()
    with conn.cursor(row_factory=class_row(ProjectAssignment)) as cur:
        cur.execute(
            """
            SELECT p.id, p.name, p.description, ep.completed_at
            FROM projects p
            JOIN employee_projects ep ON ep.project_id = p.id
            WHERE ep.employee_id = %s
            ORDER BY p.name
            """,
            (employee_id,),
        )
        return cur.fetchall()


def attach_project(employee_id: int, project_id: int, completed_at=UNSET) -> bool:
    """Links a project to an employee, optionally setting completed_at.

    Idempotent, but not a pure ON CONFLICT DO NOTHING like
    skill_repository.attach_skill — employee_projects carries a real
    field (completed_at) that a repeat call might legitimately be trying
    to change. So: insert if missing (with whatever completed_at was
    given, or NULL); if it already existed AND completed_at was
    explicitly given, update it. If it already existed and completed_at
    was NOT given, true no-op — the existing value is left alone.

    Also the low-level upsert PUT /employees/{id}/projects/{project_id}
    uses (see project_service.update_completion) — that endpoint always
    passes an explicit completed_at, so it always updates-or-creates.

    Returns:
        bool: True if a NEW employee_projects row was created — the
        caller uses this to choose 201 vs 200, same as skills' attach.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO employee_projects (employee_id, project_id, completed_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (employee_id, project_id) DO NOTHING",
            (employee_id, project_id, None if completed_at is UNSET else completed_at),
        )
        created = cur.rowcount > 0

    if not created and completed_at is not UNSET:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE employee_projects SET completed_at = %s WHERE employee_id = %s AND project_id = %s",
                (completed_at, employee_id, project_id),
            )

    return created


def detach_project(employee_id: int, project_id: int) -> None:
    """Unlinks a project from an employee. Idempotent by nature — same
    reasoning as skill_repository.detach_skill: a join row, not an
    entity, so there's no "not found" to report.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM employee_projects WHERE employee_id = %s AND project_id = %s", (employee_id, project_id)
        )
