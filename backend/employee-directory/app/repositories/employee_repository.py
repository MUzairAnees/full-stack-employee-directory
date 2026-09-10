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

# Sentinel distinguishing "field not included in this update at all" (do
# not touch it) from "field included, and is null" (clear it). Only
# phone and team_id need this: first_name/last_name/role/work_location_id/
# expertise_id/project_availability are never legitimately submitted as
# an explicit null, so plain `is not None` covers them.
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
    request, rather than trusting the JWT payload. Also used by
    team_repository to look up a manager nominee — deliberately not
    promoted alongside compute_manager_id/get_ceo_id below, since it was
    already public.
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
    department delete-guard.
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
    compute_manager_id), so they correctly appear here alongside actual
    managers when manager_id is the CEO's id — not a bug to filter out.
    """
    return list_employees(manager_id=manager_id)


def get_ceo_id(conn) -> int:
    """The single active CEO's id. There is always exactly one —
    schema.sql's idx_employees_one_active_ceo enforces it and the CEO
    can never be deactivated (soft_delete_employee).

    Public (promoted from _get_ceo_id in slice 5): team_repository needs
    it too — for pooling a released manager, and for a newly-nominated
    manager's own manager_id. Takes the caller's connection rather than
    opening its own, so it always participates in whatever transaction
    the caller is already inside.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM employees WHERE role = 'CEO'")
        row = cur.fetchone()
    assert row is not None, "no CEO row exists - seed.sql should have created one"
    return row[0]


def compute_manager_id(conn, role: str, team_id: int | None) -> int | None:
    """The org-chart derivation. Never settable directly by a caller —
    called from every write path that touches team_id or role — which is
    what makes a manager_id cycle structurally impossible: every chain is
    at most IC -> manager -> CEO.

        role = CEO      -> None (caller also forces team_id to None)
        role = MANAGER  -> the CEO's id
        anyone else     -> their team's manager, or the CEO's id if
                           they have no team (including ADMIN)

    Public (promoted from _compute_manager_id in slice 5): team_repository
    needs the exact same derivation for team create/replace/delete — one
    source, not a second copy, same reasoning as the BCRYPT_ROUNDS move
    to app/config.py in slice 4.
    """
    if role == Role.CEO:
        return None
    if role == Role.MANAGER:
        return get_ceo_id(conn)
    if team_id is not None:
        with conn.cursor() as cur:
            cur.execute("SELECT manager_id FROM teams WHERE id = %s", (team_id,))
            row = cur.fetchone()
        if row is not None:
            return row[0]
    return get_ceo_id(conn)


def _manages_active_team(conn, employee_id: int) -> bool:
    """True if this employee is the manager of an active team.

    Stays private: only used internally, for the role-change demotion
    guard below and the team_id LOCK guard. team_repository never needs
    it directly — every nominee it validates is already required to have
    role EMPLOYEE, which structurally rules this out (see
    team_repository._require_eligible_nominee).
    """
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
    assignment isn't a capability POST /employees has, ever (see
    app/schemas/employee.py: role is restricted to EMPLOYEE/ADMIN here,
    so a MANAGER can never exist without a team — slice 5 section 0).
    manager_id is derived, never accepted as input (see
    compute_manager_id).

    Raises:
        DuplicateError: email (including a case variant) is already
            taken.
        InvalidReferenceError: work_location_id or expertise_id doesn't
            reference a real row — names which one.
    """
    email = email.strip().lower()
    conn = get_connection()
    manager_id = compute_manager_id(conn, role, team_id=None)

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


def _require_active_team_or_raise(conn, team_id: int) -> None:
    """Guards the one FK a plain foreign-key constraint can't cover:
    team_id can reference a row that exists but is soft-deleted. Same
    reasoning as team_repository's department check — a caller placing
    someone onto a dead team would be invisible to every guard that
    assumes an active team has an active manager.

    422, not 409: consistent with the rest of this slice's "inactive
    reference" handling — it also means a caller can't distinguish
    "never existed" from "was deleted" from the response alone, which is
    what soft delete is supposed to mean to the outside world.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT is_active FROM teams WHERE id = %s", (team_id,))
        row = cur.fetchone()
    if row is None or not row[0]:
        raise InvalidReferenceError("team_id", "team_id does not reference an active team")


def update_employee(
    employee_id: int,
    first_name: str | None = None,
    last_name: str | None = None,
    phone=UNSET,
    role: str | None = None,
    work_location_id: int | None = None,
    project_availability: bool | None = None,
    expertise_id: int | None = None,
    team_id=UNSET,
) -> Employee:
    """Updates an employee. Which fields a given caller may submit is
    authorization, decided in employee_service, not here — this applies
    whichever fields were given and enforces the guards that depend on
    database state, not on who's asking. The SET clause stays a fixed,
    hardcoded set of "if field is not None/UNSET" branches, not a loop
    over changed fields: a loop deriving column names from input is
    exactly the identifier-injection shape parameterization doesn't
    cover.

    A role change recomputes manager_id (see compute_manager_id) and, if
    it would move someone away from MANAGER while they still manage an
    active team, is rejected outright. As of slice 5 this guard is no
    longer dormant: role MANAGER now only ever exists while its holder
    manages an active team (section 0's invariant — team_repository is
    the only path that sets or clears it), so this condition is
    equivalent to "always block moving a current MANAGER away from
    MANAGER through this endpoint" — direct demotion, like direct
    promotion, doesn't exist; both fall out of team operations only.

    A team_id change is LOCKED for anyone who currently manages an
    active team — not just for that manager, for every caller, Admin
    included: the only path that reassigns a team's manager is
    PUT /teams. Otherwise recomputes manager_id the same way
    compute_manager_id derives it anywhere else (their new team's
    manager, or the CEO if released to NULL), and — for a non-NULL
    value — requires the target team to exist and be active.

    Raises:
        NotFoundError: no such employee.
        DependentsExistError: role change would leave an active team
            without the manager it was pointing at; or a team_id change
            was attempted for someone who currently manages an active
            team (see LOCK above).
        InvalidReferenceError: team_id names a team that doesn't exist
            or isn't active.
        DuplicateError: email conflict (not reachable via this function
            yet — email isn't self/Admin/Manager-editable this slice).
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
    if work_location_id is not None:
        updates.append("work_location_id = %s")
        params.append(work_location_id)
    if project_availability is not None:
        updates.append("project_availability = %s")
        params.append(project_availability)
    if expertise_id is not None:
        updates.append("expertise_id = %s")
        params.append(expertise_id)
    if role is not None:
        if current.role == Role.MANAGER and role != Role.MANAGER and _manages_active_team(conn, employee_id):
            raise DependentsExistError(
                f"employee {employee_id} manages an active team and cannot be reassigned away from MANAGER"
            )
        manager_id = compute_manager_id(conn, role, current.team_id)
        updates.append("role = %s")
        params.append(role)
        updates.append("manager_id = %s")
        params.append(manager_id)
    if team_id is not UNSET:
        if _manages_active_team(conn, employee_id):
            raise DependentsExistError(
                f"employee {employee_id} manages an active team; reassign the team's manager via PUT /teams instead"
            )
        if team_id is not None:
            _require_active_team_or_raise(conn, team_id)
        new_manager_id = compute_manager_id(conn, current.role, team_id)
        updates.append("team_id = %s")
        params.append(team_id)
        updates.append("manager_id = %s")
        params.append(new_manager_id)

    if not updates:
        return current

    updates.append("updated_at = now()")
    params.append(employee_id)

    try:
        with conn.cursor(row_factory=class_row(Employee)) as cur:
            cur.execute(
                f"UPDATE employees SET {', '.join(updates)} WHERE id = %s RETURNING {_COLUMNS}",
                params,
            )
            return cur.fetchone()
    except psycopg.errors.ForeignKeyViolation as err:
        conn.rollback()
        raise _translate_fk_violation(err) from err


def soft_delete_employee(employee_id: int) -> Employee:
    """Deactivates an employee, or no-ops if already inactive — the
    already-inactive check runs BEFORE any guard, same reasoning as
    department_repository.soft_delete_department: idempotent means
    idempotent regardless of what changes around it later.

    If the employee is a MANAGER (only reachable once the active-reports
    guard below has already passed — meaning no active member OTHER than
    themselves is left on their team), deactivating them also deactivates
    their now-manager-less team, in the SAME transaction: teams.manager_id
    is NOT NULL and cannot be left pointing at an inactive person. This is
    the first multi-statement, genuinely atomic write in this codebase —
    see the comment on conn.transaction() usage below.

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

    # conn.transaction(): the connection is autocommit=True (app/repositories/db.py)
    # and, until this slice, every write here has been a single statement —
    # autocommit alone made each one atomic on its own. This is the first
    # operation that must NOT partially apply: deactivating the employee
    # without also deactivating their team (or vice versa) leaves
    # teams.manager_id pointing at an inactive person. conn.transaction()
    # temporarily suspends autocommit for the block, issuing a real
    # BEGIN, and COMMITs on a clean exit or ROLLBACKs on an exception —
    # unlike the except blocks elsewhere in this file, nothing inside this
    # block calls conn.rollback() itself; that's the context manager's job.
    with conn.transaction():
        with conn.cursor(row_factory=class_row(Employee)) as cur:
            cur.execute(
                f"UPDATE employees SET is_active = false, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
                (employee_id,),
            )
            employee = cur.fetchone()
        if employee.role == Role.MANAGER:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE teams SET is_active = false, updated_at = now() WHERE manager_id = %s AND is_active",
                    (employee_id,),
                )

    return employee
