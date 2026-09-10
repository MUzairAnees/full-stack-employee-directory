"""Local test defaults for the POSTGRES_*/IS_LOCAL env vars Terraform
normally injects (see infra/locals.tf). Only fills in values that aren't
already set, so it never overrides real configuration — it exists purely
so `pytest` works out of the box against the local Postgres instance
every participant already has running (see docs/validation.md).
"""

import os

os.environ.setdefault("IS_LOCAL", "true")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_NAME", "postgres")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASS", "postgres123")


def hard_delete_departments(conn, department_ids: list[int]) -> None:
    """Hard-deletes departments by id — test teardown only; the real
    DELETE /departments always soft-deletes. Nothing references
    departments.id except teams.department_id, so this is safe on its
    own as long as any teams created in the same test are torn down
    first (hard_delete_teams).
    """
    if not department_ids:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM departments WHERE id = ANY(%s)", (department_ids,))


def hard_delete_teams(conn, team_ids: list[int]) -> None:
    """Hard-deletes teams by id — test teardown only; there is no
    user-facing hard-delete anywhere in the app, DELETE /teams always
    soft-deletes.

    Clears employees.team_id for anyone still pointing at these teams
    first (their manager_id is left as-is; pair with
    hard_delete_employees for the employees themselves). Call this
    BEFORE hard_delete_employees when a test created both a team and its
    manager — the team's manager_id FK would otherwise block deleting
    the employee first.
    """
    if not team_ids:
        return
    with conn.cursor() as cur:
        cur.execute("UPDATE employees SET team_id = NULL WHERE team_id = ANY(%s)", (team_ids,))
        cur.execute("DELETE FROM teams WHERE id = ANY(%s)", (team_ids,))


def hard_delete_employees(conn, employee_ids: list[int]) -> None:
    """Hard-deletes employees by id — test teardown only; the real
    DELETE /employees always soft-deletes (see employee_repository).

    employees.manager_id is self-referencing (a plain FK, no ON DELETE
    clause — RESTRICT by default), so an employee in this set who is
    another employee in this set's manager_id would block the DELETE.
    Cleared first, safe regardless of what order the ids were created
    in or what pointed at what. Also clears any employee_skills rows for
    these employees (slice 6) — same RESTRICT-by-default reasoning;
    leaves the skills rows themselves alone (pair with hard_delete_skills
    for those, when a test also created skill rows to clean up).
    """
    if not employee_ids:
        return
    with conn.cursor() as cur:
        cur.execute("UPDATE employees SET manager_id = NULL WHERE manager_id = ANY(%s)", (employee_ids,))
        cur.execute("DELETE FROM employee_skills WHERE employee_id = ANY(%s)", (employee_ids,))
        cur.execute("DELETE FROM employees WHERE id = ANY(%s)", (employee_ids,))


def hard_delete_skills(conn, skill_ids: list[int]) -> None:
    """Hard-deletes skills by id — test teardown only; there is no
    user-facing delete for skills at all, attach/detach only ever touch
    the employee_skills join. Clears any employee_skills rows
    referencing these skills first (skills.id has no ON DELETE clause,
    RESTRICT by default).
    """
    if not skill_ids:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM employee_skills WHERE skill_id = ANY(%s)", (skill_ids,))
        cur.execute("DELETE FROM skills WHERE id = ANY(%s)", (skill_ids,))


def make_function_url_event(raw_path: str) -> dict:
    """Builds a fake Lambda Function URL event (payload format 2.0) for a
    given raw path, so tests can invoke function.handler() directly with
    the exact shape AWS sends — CloudFront forwards the full,
    "/api/employee-directory"-prefixed path unstripped; the local proxy
    strips it before the Lambda ever sees the request. Shared here so
    every test that needs to prove both shapes resolve the same way
    doesn't hand-build this event from scratch.
    """
    return {
        "version": "2.0",
        "rawPath": raw_path,
        "rawQueryString": "",
        "headers": {"host": "example.lambda-url.us-east-2.on.aws"},
        "requestContext": {
            "http": {
                "method": "GET",
                "path": raw_path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "domainName": "example.lambda-url.us-east-2.on.aws",
            "requestId": "test-request-id",
            "time": "01/Jan/2026:00:00:00 +0000",
            "timeEpoch": 1735689600,
        },
        "isBase64Encoded": False,
    }
