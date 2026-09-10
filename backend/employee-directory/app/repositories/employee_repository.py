"""Data access for employees."""

import psycopg
from psycopg.rows import class_row

from app.exceptions import DependentsExistError, DuplicateError, InvalidReferenceError, NotFoundError
from app.models.employee import Employee
from app.models.role import Role
from app.repositories.db import get_connection

_COLUMNS = (
    "id, first_name, last_name, email, phone, password_hash, role, "
    "work_location_id, team_id, manager_id, expertise_id, project_availability, "
    "is_active, created_at, updated_at"
)

# Sentinel distinguishing "phone not included in this update at all" (do
# not touch it) from "phone included, and is null" (clear it). Only
# phone needs this: first_name/last_name/role are never legitimately
# submitted as an explicit null, so plain `is not None` covers them.
UNSET = object()

_FK_CONSTRAINT_TO_FIELD = {
    "employees_work_location_id_fkey": "work_location_id",
    "employees_expertise_id_fkey": "expertise_id",
    "employees_manager_id_fkey": "manager_id",
    "employees_team_id_fkey": "team_id",
}


def get_employee_by_email(email: str) -> Employee | None:
    """Returns the employee with this email, or None if none exists.

    Matches on LOWER(email), not email — see schema.sql's
    idx_employees_email_lower and the commit that added it: a row ever
    stored with mixed case must still be reachable.

    Unlike get_employee, this returns None rather than raising
    NotFoundError: login needs to tell "no such email" apart from other
    conditions itself, on the way to an identical, generic 401 (see
    auth_service.authenticate).
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Employee)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM employees WHERE LOWER(email) = %s", (email,))
        return cur.fetchone()


def get_employee_by_id(employee_id: int) -> Employee | None:
    """Returns the employee with this id, or None if none exists.

    Used by the current_user dependency to re-read the employee (and in
    particular is_active) from the database on every authenticated
    request, rather than trusting the JWT payload.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Employee)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM employees WHERE id = %s", (employee_id,))
        return cur.fetchone()


def get_employee(employee_id: int) -> Employee:
    """Returns the employee with this id — active or not.

    Raises:
        NotFoundError: If no employee has that id at all.
    """
    employee = get_employee_by_id(employee_id)
    if employee is None:
        raise NotFoundError(f"employee {employee_id} not found")
    return employee


def list_employees(
    *,
    q: str | None = None,
    location_id: int | None = None,
    expertise_id: int | None = None,
    manager_id: int | None = None,
    team_id: int | None = None,
    department_id: int | None = None,
    available: bool | None = None,
    include_inactive: bool = False,
) -> list[Employee]:
    """Searches/filters employees. Every condition is a hardcoded literal
    gated by a named parameter — never built from iterating a dict of
    arbitrary keys — so there's no identifier-injection surface here
    regardless of how many filters this grows to.

    department_id filters through teams (a subquery, not stored on
    employees directly — see schema.sql's comment on why), same as the
    department delete-guard; like team_id, it's real and correct now but
    can't return anything until slice 5 populates teams.
    """
    conditions: list[str] = []
    params: list = []

    if not include_inactive:
        conditions.append("is_active")
    if q is not None:
        conditions.append("(first_name ILIKE %s OR last_name ILIKE %s OR email ILIKE %s)")
        pattern = f"%{q}%"
        params.extend([pattern, pattern, pattern])
    if location_id is not None:
        conditions.append("work_location_id = %s")
        params.append(location_id)
    if expertise_id is not None:
        conditions.append("expertise_id = %s")
        params.append(expertise_id)
    if manager_id is not None:
        conditions.append("manager_id = %s")
        params.append(manager_id)
    if team_id is not None:
        conditions.append("team_id = %s")
        params.append(team_id)
    if department_id is not None:
        conditions.append("team_id IN (SELECT id FROM teams WHERE department_id = %s)")
        params.append(department_id)
    if available is not None:
        conditions.append("project_availability = %s")
        params.append(available)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Employee)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM employees {where} ORDER BY last_name, first_name", params)
        return cur.fetchall()


def get_reports(manager_id: int) -> list[Employee]:
    """Direct reports: everyone whose manager_id is this employee's id.

    An employee with no team has manager_id = the CEO (see
    _compute_manager_id), so they correctly appear here alongside actual
    managers when manager_id is the CEO's id — not a bug to filter out.
    """
    return list_employees(manager_id=manager_id)


def _get_ceo_id(conn) -> int:
    """The single active CEO's id. There is always exactly one —
    schema.sql's idx_employees_one_active_ceo enforces it and the CEO
    can never be deactivated (soft_delete_employee).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM employees WHERE role = 'CEO'")
        row = cur.fetchone()
    assert row is not None, "no CEO row exists - seed.sql should have created one"
    return row[0]


def _compute_manager_id(conn, role: str, team_id: int | None) -> int | None:
    """The org-chart derivation. Never settable directly by a caller —
    called from every write path that touches team_id or role — which is
    what makes a manager_id cycle structurally impossible: every chain is
    at most IC -> manager -> CEO.

        role = CEO      -> None (caller also forces team_id to None)
        role = MANAGER  -> the CEO's id
        anyone else     -> their team's manager, or the CEO's id if
                           they have no team (including ADMIN)
    """
    if role == Role.CEO:
        return None
    if role == Role.MANAGER:
        return _get_ceo_id(conn)
    if team_id is not None:
        with conn.cursor() as cur:
            cur.execute("SELECT manager_id FROM teams WHERE id = %s", (team_id,))
            row = cur.fetchone()
        if row is not None:
            return row[0]
    return _get_ceo_id(conn)


def _manages_active_team(conn, employee_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM teams WHERE manager_id = %s AND is_active)", (employee_id,))
        return cur.fetchone()[0]


def _translate_unique_violation(err: psycopg.errors.UniqueViolation, email: str) -> DuplicateError:
    constraint = err.diag.constraint_name
    if constraint == "idx_employees_one_active_ceo":
        return DuplicateError("an active CEO already exists")
    return DuplicateError(f"an employee with email '{email}' already exists")


def _translate_fk_violation(err: psycopg.errors.ForeignKeyViolation) -> InvalidReferenceError:
    constraint = err.diag.constraint_name
    field = _FK_CONSTRAINT_TO_FIELD.get(constraint, "unknown")
    return InvalidReferenceError(field, f"{field} does not reference an existing record")


def create_employee(
    first_name: str,
    last_name: str,
    email: str,
    password_hash: str,
    role: str,
    work_location_id: int,
    expertise_id: int,
    phone: str | None = None,
    project_availability: bool = True,
) -> Employee:
    """Creates an employee. team_id is always NULL at creation — team
    assignment isn't a capability that exists yet (slice 5's
    "CEO creates the team around them" flow sets it later); manager_id
    is derived, never accepted as input (see _compute_manager_id).
    A MANAGER created this way legitimately has team_id NULL — the
    transient state before slice 5 builds a team around them.

    Raises:
        DuplicateError: email (including a case variant) is already
            taken, or role=CEO was requested while an active CEO exists.
        InvalidReferenceError: work_location_id or expertise_id doesn't
            reference a real row — names which one.
    """
    email = email.strip().lower()
    conn = get_connection()
    manager_id = _compute_manager_id(conn, role, team_id=None)

    try:
        with conn.cursor(row_factory=class_row(Employee)) as cur:
            cur.execute(
                f"""
                INSERT INTO employees (
                    first_name, last_name, email, phone, password_hash, role,
                    work_location_id, team_id, manager_id, expertise_id, project_availability
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s)
                RETURNING {_COLUMNS}
                """,
                (
                    first_name,
                    last_name,
                    email,
                    phone,
                    password_hash,
                    role,
                    work_location_id,
                    manager_id,
                    expertise_id,
                    project_availability,
                ),
            )
            return cur.fetchone()
    except psycopg.errors.UniqueViolation as err:
        conn.rollback()
        raise _translate_unique_violation(err, email) from err
    except psycopg.errors.ForeignKeyViolation as err:
        conn.rollback()
        raise _translate_fk_violation(err) from err


def update_employee(
    employee_id: int,
    first_name: str | None = None,
    last_name: str | None = None,
    phone=UNSET,
    role: str | None = None,
) -> Employee:
    """Updates an employee. Which fields to touch is the caller's
    decision (authorization lives in employee_service, not here) — this
    just applies whichever of first_name/last_name/phone/role were
    given. The SET clause stays a fixed, hardcoded set of "if field is
    not None/UNSET" branches, not a loop over changed fields: a loop
    deriving column names from input is exactly the identifier-injection
    shape parameterization doesn't cover.

    A role change recomputes manager_id (see _compute_manager_id) and,
    if it would move someone away from MANAGER while they still manage
    an active team, is rejected outright — that guard can't fire yet
    (no teams exist), same treatment as the department delete-guard.

    Raises:
        NotFoundError: no such employee.
        DependentsExistError: role change would leave an active team
            without the manager it was pointing at.
        DuplicateError: email conflict (not reachable via this
            function yet — email isn't self/Admin-editable this slice).
    """
    conn = get_connection()
    current = get_employee(employee_id)

    updates: list[str] = []
    params: list = []

    if first_name is not None:
        updates.append("first_name = %s")
        params.append(first_name)
    if last_name is not None:
        updates.append("last_name = %s")
        params.append(last_name)
    if phone is not UNSET:
        updates.append("phone = %s")
        params.append(phone)
    if role is not None:
        if current.role == Role.MANAGER and role != Role.MANAGER and _manages_active_team(conn, employee_id):
            raise DependentsExistError(
                f"employee {employee_id} manages an active team and cannot be reassigned away from MANAGER"
            )
        manager_id = _compute_manager_id(conn, role, current.team_id)
        updates.append("role = %s")
        params.append(role)
        updates.append("manager_id = %s")
        params.append(manager_id)

    if not updates:
        return current

    updates.append("updated_at = now()")
    params.append(employee_id)

    with conn.cursor(row_factory=class_row(Employee)) as cur:
        cur.execute(
            f"UPDATE employees SET {', '.join(updates)} WHERE id = %s RETURNING {_COLUMNS}",
            params,
        )
        return cur.fetchone()


def soft_delete_employee(employee_id: int) -> Employee:
    """Deactivates an employee, or no-ops if already inactive — the
    already-inactive check runs BEFORE any guard, same reasoning as
    department_repository.soft_delete_department: idempotent means
    idempotent regardless of what changes around it later.

    Raises:
        NotFoundError: no such employee.
        DependentsExistError: the CEO (can never be deactivated), the
            last active Admin, or anyone with active direct reports.
    """
    employee = get_employee(employee_id)
    if not employee.is_active:
        return employee

    if employee.role == Role.CEO:
        raise DependentsExistError("the CEO cannot be deactivated")

    conn = get_connection()

    if employee.role == Role.ADMIN:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM employees WHERE role = 'ADMIN' AND is_active")
            active_admin_count = cur.fetchone()[0]
        if active_admin_count <= 1:
            raise DependentsExistError("at least one active Admin must remain")

    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM employees WHERE manager_id = %s AND is_active)", (employee_id,))
        if cur.fetchone()[0]:
            raise DependentsExistError(f"employee {employee_id} has active direct reports and cannot be deactivated")

    with conn.cursor(row_factory=class_row(Employee)) as cur:
        cur.execute(
            f"UPDATE employees SET is_active = false, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
            (employee_id,),
        )
        return cur.fetchone()
