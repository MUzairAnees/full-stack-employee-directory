"""Data access for teams.

Deliberately does not import department_repository or duplicate its SQL —
it calls get_department() for the one thing it needs (existence +
is_active), the same way every other cross-table check in this codebase
(e.g. department_repository._has_active_employees) writes its own direct
SQL rather than reaching into another repository's internals. The one
exception is employee_repository: team creation/replacement/deletion all
need to write employees rows in the same transaction as the teams row,
so this module imports employee_repository's promoted helpers
(get_employee_by_id, compute_manager_id, get_ceo_id) rather than
duplicating the org-chart derivation — see employee_repository.py's
docstrings on why those were promoted in this slice. The dependency runs
one way only: employee_repository never imports team_repository.
"""

from datetime import date

import psycopg
from psycopg.rows import class_row

from app.exceptions import DependentsExistError, DuplicateError, InvalidReferenceError, NotFoundError
from app.models.role import Role
from app.models.team import Achievement, Team
from app.repositories.db import get_connection
from app.repositories.department_repository import get_department
from app.repositories.employee_repository import compute_manager_id, get_ceo_id, get_employee_by_id

_COLUMNS = "id, name, department_id, manager_id, is_active, created_at, updated_at"


def list_teams(*, department_id: int | None = None, include_inactive: bool = False) -> list[Team]:
    """Returns teams, ordered by name.

    Args:
        department_id: If given, only teams in that department.
        include_inactive: If False (default), soft-deleted teams are
            excluded.
    """
    conditions: list[str] = []
    params: list = []
    if not include_inactive:
        conditions.append("is_active")
    if department_id is not None:
        conditions.append("department_id = %s")
        params.append(department_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = get_connection()
    with conn.cursor(row_factory=class_row(Team)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM teams {where} ORDER BY name", params)
        return cur.fetchall()


def get_team(team_id: int) -> Team:
    """Returns a team by id — active or not. Like department/employee
    get-by-id, a direct id request ignores is_active: 410 means "no such
    id", never "found but inactive" — hiding inactive rows here would
    make a soft-deleted team's own detail view unreachable.

    Raises:
        NotFoundError: If no team has that id at all.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Team)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM teams WHERE id = %s", (team_id,))
        team = cur.fetchone()
        if team is None:
            raise NotFoundError(f"team {team_id} not found")
        return team


def _require_active_department_or_raise(department_id: int) -> None:
    """A plain FK can't catch "exists but soft-deleted" — see the
    identical reasoning on employee_repository._require_active_team_or_raise.
    Translates department_repository's NotFoundError (missing) and an
    explicit is_active check (inactive) to the SAME InvalidReferenceError,
    for the same leak-prevention reason: a caller shouldn't be able to
    tell "never existed" from "was deleted" from the response.
    """
    try:
        department = get_department(department_id)
    except NotFoundError as err:
        raise InvalidReferenceError("department_id", "department_id does not reference an existing department") from err
    if not department.is_active:
        raise InvalidReferenceError("department_id", "department_id does not reference an active department")


def _require_eligible_nominee(nominee, *, current_team_id: int | None) -> None:
    """Guards who can be nominated/renominated as a team's manager, for
    both POST /teams (current_team_id=None: any existing assignment
    disqualifies) and PUT /teams replacement (current_team_id=the team
    being updated: already being on THIS team is fine, a different one
    isn't).

    Every one of these is deliberately the SAME exception class
    (DuplicateError, 409) and the SAME "not eligible" framing, whether
    the reason is a role that isn't EMPLOYEE (ADMIN, CEO, or an existing
    MANAGER of somewhere else — role MANAGER structurally implies
    managing an active team, per section 0, so this one check covers
    both) or an existing assignment to a different team. A caller
    shouldn't be able to distinguish these reasons from the response any
    more finely than "this employee can't be nominated right now."

    Raises:
        InvalidReferenceError: manager_id doesn't reference an existing
            employee at all (422 — the id itself is bad).
        DuplicateError: the employee exists but isn't eligible (409 — the
            id is fine, the employee's current state isn't).
    """
    if nominee is None:
        raise InvalidReferenceError("manager_id", "manager_id does not reference an existing employee")
    if nominee.role != Role.EMPLOYEE:
        raise DuplicateError(f"employee {nominee.id} cannot be nominated as manager (current role must be EMPLOYEE)")
    if nominee.team_id is not None and nominee.team_id != current_team_id:
        raise DuplicateError(f"employee {nominee.id} is already assigned to a different team")


def _translate_unique_violation(err: psycopg.errors.UniqueViolation, name: str) -> DuplicateError:
    constraint = err.diag.constraint_name
    if constraint == "idx_teams_one_active_manager":
        return DuplicateError("this employee already manages another active team")
    if constraint == "teams_department_id_name_key":
        return DuplicateError(f"a team named '{name}' already exists in this department")
    return DuplicateError("a uniqueness constraint was violated")


def create_team(name: str, department_id: int, manager_id: int) -> Team:
    """Creates a team and, in the SAME transaction, promotes the
    nominee: role -> MANAGER, team_id -> this team, manager_id -> the
    CEO. This is a write PERFORMED BY THE OPERATION, not a permission
    granted to whoever calls it — the CEO (the only caller who can reach
    this, via require_role) still cannot call PUT /employees/{id}
    themselves; this is the system doing the org-chart bookkeeping a
    team's existence implies, not the CEO exercising employee-edit
    rights.

    Raises:
        InvalidReferenceError: department_id doesn't reference an
            active department, or manager_id doesn't reference an
            existing employee.
        DuplicateError: manager_id names an employee not eligible to be
            nominated (see _require_eligible_nominee), or the team name
            collides within this department.
    """
    conn = get_connection()
    _require_active_department_or_raise(department_id)
    nominee = get_employee_by_id(manager_id)
    _require_eligible_nominee(nominee, current_team_id=None)
    ceo_id = get_ceo_id(conn)

    try:
        with conn.transaction():
            with conn.cursor(row_factory=class_row(Team)) as cur:
                cur.execute(
                    f"""
                    INSERT INTO teams (name, department_id, manager_id)
                    VALUES (%s, %s, %s)
                    RETURNING {_COLUMNS}
                    """,
                    (name, department_id, manager_id),
                )
                team = cur.fetchone()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE employees SET role = 'MANAGER', team_id = %s, manager_id = %s, updated_at = now() "
                    "WHERE id = %s",
                    (team.id, ceo_id, manager_id),
                )
        return team
    except psycopg.errors.UniqueViolation as err:
        raise _translate_unique_violation(err, name) from err


def update_team(
    team_id: int,
    name: str | None = None,
    manager_id: int | None = None,
    department_id: int | None = None,
) -> Team:
    """Updates a team's name, department, and/or manager.

    A submitted manager_id equal to the team's CURRENT manager is a
    no-op for the manager change specifically (name/department_id, if
    also given, still apply) — running the promote/demote logic on the
    same person would point their manager_id at themselves via the bulk
    "everyone else" update, which the org chart forbids.

    Otherwise, in ONE transaction: the incoming employee is promoted
    (role -> MANAGER, manager_id -> the CEO, team_id -> this team — a
    no-op if already a member, required if they came from the pool); the
    outgoing employee is demoted (role -> EMPLOYEE, team_id UNCHANGED —
    they stay on the team as an IC) with their manager_id repointed at
    the incoming employee, same as every other pre-existing member's
    (one bulk UPDATE, not a per-row loop through compute_manager_id —
    this does not require the team to be empty).

    Raises:
        NotFoundError: no such team.
        InvalidReferenceError: department_id doesn't reference an active
            department, or manager_id doesn't reference an existing
            employee.
        DuplicateError: manager_id names an employee not eligible to be
            (re)nominated, or the new name collides within the
            (possibly new) department.
    """
    conn = get_connection()
    current = get_team(team_id)

    if department_id is not None:
        _require_active_department_or_raise(department_id)

    manager_change = manager_id is not None and manager_id != current.manager_id
    outgoing_id = current.manager_id
    if manager_change:
        incoming = get_employee_by_id(manager_id)
        _require_eligible_nominee(incoming, current_team_id=team_id)
        ceo_id = get_ceo_id(conn)

    updates: list[str] = []
    params: list = []
    if name is not None:
        updates.append("name = %s")
        params.append(name)
    if department_id is not None:
        updates.append("department_id = %s")
        params.append(department_id)
    if manager_change:
        updates.append("manager_id = %s")
        params.append(manager_id)

    if not updates:
        return current

    updates.append("updated_at = now()")
    team_params = [*params, team_id]

    try:
        with conn.transaction():
            if manager_change:
                # Everyone currently on the team except the incoming
                # manager gets repointed at them — this naturally covers
                # both the outgoing manager (still on the team as an IC)
                # and every other member, in one statement. Excluding
                # incoming by id, not by "team_id != this team", because
                # incoming might already BE a member (promoted from
                # within) — if so this WHERE would otherwise catch them
                # too and point their manager_id at themselves.
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE employees SET manager_id = %s, updated_at = now() "
                        "WHERE team_id = %s AND id != %s",
                        (manager_id, team_id, manager_id),
                    )
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE employees SET role = 'EMPLOYEE', updated_at = now() WHERE id = %s",
                        (outgoing_id,),
                    )
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE employees SET role = 'MANAGER', manager_id = %s, team_id = %s, updated_at = now() "
                        "WHERE id = %s",
                        (ceo_id, team_id, manager_id),
                    )
            with conn.cursor(row_factory=class_row(Team)) as cur:
                cur.execute(
                    f"UPDATE teams SET {', '.join(updates)} WHERE id = %s RETURNING {_COLUMNS}",
                    team_params,
                )
                return cur.fetchone()
    except psycopg.errors.UniqueViolation as err:
        raise _translate_unique_violation(err, name or current.name) from err


def soft_delete_team(team_id: int) -> Team:
    """Deactivates a team, or no-ops if already inactive.

    Allowed only when there are no active members OTHER than the
    manager — the manager counts as a member (their own team_id points
    at this team), so "empty" can't mean zero, or a team could never be
    deleted at all.

    In the SAME transaction: the team is deactivated, and its manager is
    released to the pool (team_id -> NULL, role -> EMPLOYEE, manager_id
    -> the CEO) — the person survives, the team doesn't; they're eligible
    to be nominated again later.

    Raises:
        NotFoundError: no such team.
        DependentsExistError: active members other than the manager
            exist.
    """
    team = get_team(team_id)
    if not team.is_active:
        return team

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM employees WHERE team_id = %s AND is_active AND id != %s)",
            (team_id, team.manager_id),
        )
        if cur.fetchone()[0]:
            raise DependentsExistError(f"team {team_id} has active members other than its manager and cannot be deleted")

    ceo_id = get_ceo_id(conn)
    with conn.transaction():
        with conn.cursor(row_factory=class_row(Team)) as cur:
            cur.execute(
                f"UPDATE teams SET is_active = false, updated_at = now() WHERE id = %s RETURNING {_COLUMNS}",
                (team_id,),
            )
            team = cur.fetchone()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE employees SET team_id = NULL, role = 'EMPLOYEE', manager_id = %s, updated_at = now() "
                "WHERE id = %s",
                (ceo_id, team.manager_id),
            )
    return team


def get_team_achievements(team_id: int, month: str | None = None) -> list[Achievement]:
    """Completed projects for this team's CURRENT active members. month
    ("YYYY-MM"), already validated at the controller (a FastAPI Query
    pattern constraint, not re-checked here), narrows to that month;
    omitted means all-time — that's what answers "total done ever," not
    just "what shipped this month".

    completed_at IS NOT NULL is explicit and load-bearing: an
    employee_projects row with no completion date is in-progress work,
    not an achievement — that's what "reopen by clearing completed_at"
    (see project_repository.attach_project/project_service.update_completion)
    means it stops counting as.

    Indexing note, verified by name (not assumed from either a prior
    claim or notes describing it differently): employee_projects has TWO
    separate single-column indexes — idx_employee_projects_project_id
    and idx_employee_projects_completed_at — NOT one composite index
    covering both. The actual indexed path this query walks is
    employees.team_id (idx_employees_team_id) to find the team's
    members, then employee_projects via its primary key
    (employee_id, project_id), whose leading column is employee_id.

    Raises:
        NotFoundError: no team has this id (410).
    """
    get_team(team_id)  # raises NotFoundError if missing

    conditions = ["e.team_id = %s", "e.is_active", "ep.completed_at IS NOT NULL"]
    params: list = [team_id]

    if month is not None:
        year, month_number = (int(part) for part in month.split("-"))
        start = date(year, month_number, 1)
        end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)
        conditions.append("ep.completed_at >= %s AND ep.completed_at < %s")
        params.extend([start, end])

    conn = get_connection()
    with conn.cursor(row_factory=class_row(Achievement)) as cur:
        cur.execute(
            f"""
            SELECT
                e.id AS employee_id,
                e.first_name AS employee_first_name,
                e.last_name AS employee_last_name,
                p.id AS project_id,
                p.name AS project_name,
                ep.completed_at
            FROM employee_projects ep
            JOIN employees e ON e.id = ep.employee_id
            JOIN projects p ON p.id = ep.project_id
            WHERE {" AND ".join(conditions)}
            ORDER BY ep.completed_at, e.last_name, e.first_name
            """,
            params,
        )
        return cur.fetchall()
