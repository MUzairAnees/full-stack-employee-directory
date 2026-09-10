"""Tests for /employees: creation, self/manager/Admin edit rights, the
org-chart derivation, and the delete guards (CEO, last active Admin,
active direct reports, and the manager -> empty-team cascade).

Teardown is hard DELETE throughout (see conftest.hard_delete_employees/
hard_delete_teams/hard_delete_departments) — soft-deleting test rows via
the real API hides them from the default list but leaves them in the
table forever, which is exactly the debt slice 5 section 7 called out.
"""

import uuid

from fastapi.testclient import TestClient

import app.repositories.db as db
from app.main import app
from conftest import hard_delete_departments, hard_delete_employees, hard_delete_teams

client = TestClient(app)

_CEO_EMAIL = "ceo@example.com"
_CEO_PASSWORD = "ceo1234"
_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASSWORD = "admin1234"
_TEST_PASSWORD = "test-password-123"


def _token_for(email: str, password: str) -> str:
    return client.post("/login", json={"email": email, "password": password}).json()["access_token"]


def _ceo_headers() -> dict:
    return {"Authorization": f"Bearer {_token_for(_CEO_EMAIL, _CEO_PASSWORD)}"}


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_token_for(_ADMIN_EMAIL, _ADMIN_PASSWORD)}"}


def _employee_headers(email: str) -> dict:
    return {"Authorization": f"Bearer {_token_for(email, _TEST_PASSWORD)}"}


def _ceo_id() -> int:
    return client.get("/me", headers=_ceo_headers()).json()["id"]


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:10]}@example.com"


def _valid_create_body(**overrides) -> dict:
    headers = _admin_headers()
    locations = client.get("/work-locations", headers=headers).json()
    expertise_values = client.get("/expertise", headers=headers).json()
    body = {
        "first_name": "Test",
        "last_name": "Employee",
        "email": _unique_email(),
        "password": _TEST_PASSWORD,
        "role": "EMPLOYEE",
        "work_location_id": next(loc["id"] for loc in locations if loc["name"] == "Remote"),
        "expertise_id": next(v["id"] for v in expertise_values if v["name"] == "Backend"),
    }
    body.update(overrides)
    return body


def _cleanup(*, employee_ids=(), team_ids=(), department_ids=()) -> None:
    """Hard-deletes everything a test created, in FK-safe order: teams
    before employees (a team's manager_id would block deleting them
    first), departments last (nothing references them but teams).
    """
    conn = db.get_connection()
    hard_delete_teams(conn, list(team_ids))
    hard_delete_employees(conn, list(employee_ids))
    hard_delete_departments(conn, list(department_ids))


def _make_manager_with_team(*, member_count: int = 0) -> dict:
    """Creates a department, an EMPLOYEE, a team nominating them (making
    them MANAGER via POST /teams), and optionally `member_count`
    additional plain team members placed via Admin PUT. Returns
    {"department", "team", "manager", "members"} — every id the caller
    must pass to _cleanup when done.
    """
    admin_headers = _admin_headers()
    ceo_headers = _ceo_headers()

    department = client.post(
        "/departments", json={"name": f"Dept {uuid.uuid4().hex[:8]}"}, headers=ceo_headers
    ).json()
    nominee = client.post("/employees", json=_valid_create_body(), headers=admin_headers).json()
    team_response = client.post(
        "/teams",
        json={
            "name": f"Team {uuid.uuid4().hex[:8]}",
            "department_id": department["id"],
            "manager_id": nominee["id"],
        },
        headers=ceo_headers,
    )
    assert team_response.status_code == 201, team_response.text
    team = team_response.json()
    manager = client.get(f"/employees/{nominee['id']}", headers=admin_headers).json()

    members = []
    for _ in range(member_count):
        member = client.post("/employees", json=_valid_create_body(), headers=admin_headers).json()
        placed = client.put(f"/employees/{member['id']}", json={"team_id": team["id"]}, headers=admin_headers)
        assert placed.status_code == 200, placed.text
        members.append(placed.json())

    return {"department": department, "team": team, "manager": manager, "members": members}


# ---------------------------------------------------------------------
# Create: authorization
# ---------------------------------------------------------------------


def test_admin_can_create_an_employee() -> None:
    response = client.post("/employees", json=_valid_create_body(), headers=_admin_headers())
    assert response.status_code == 201
    assert response.json()["is_active"] is True

    _cleanup(employee_ids=[response.json()["id"]])


def test_create_requires_admin_role_not_just_ceo() -> None:
    """POST /employees is Admin only - literally, not CEO-or-Admin. The
    CEO is authenticated here, just the wrong role.
    """
    response = client.post("/employees", json=_valid_create_body(), headers=_ceo_headers())
    assert response.status_code == 403


def test_create_requires_authentication() -> None:
    response = client.post("/employees", json=_valid_create_body())
    assert response.status_code == 401


# ---------------------------------------------------------------------
# Create: role restriction (slice 5 section 0)
# ---------------------------------------------------------------------


def test_create_rejects_role_manager() -> None:
    """MANAGER is conferred by team assignment (POST/PUT /teams) and by
    nothing else - never pre-set. A 422 at the schema layer, before any
    of our own code runs.
    """
    response = client.post("/employees", json=_valid_create_body(role="MANAGER"), headers=_admin_headers())
    assert response.status_code == 422


def test_create_rejects_role_ceo() -> None:
    """CEO is single and seeded, never created."""
    response = client.post("/employees", json=_valid_create_body(role="CEO"), headers=_admin_headers())
    assert response.status_code == 422


# ---------------------------------------------------------------------
# Create: validation and uniqueness
# ---------------------------------------------------------------------


def test_create_with_bad_work_location_id_returns_422_naming_the_field() -> None:
    response = client.post("/employees", json=_valid_create_body(work_location_id=999999), headers=_admin_headers())
    assert response.status_code == 422
    assert response.json()["field"] == "work_location_id"


def test_create_duplicate_email_returns_409() -> None:
    body = _valid_create_body()
    first = client.post("/employees", json=body, headers=_admin_headers())
    assert first.status_code == 201

    duplicate = client.post("/employees", json=body, headers=_admin_headers())
    assert duplicate.status_code == 409

    _cleanup(employee_ids=[first.json()["id"]])


def test_create_duplicate_email_case_variant_returns_409() -> None:
    """The LOWER(email) unique index stops two rows differing only by
    case - proving that, not just the exact-match duplicate above.
    """
    body = _valid_create_body()
    first = client.post("/employees", json=body, headers=_admin_headers())
    assert first.status_code == 201

    case_variant = {**body, "email": body["email"].upper()}
    duplicate = client.post("/employees", json=case_variant, headers=_admin_headers())
    assert duplicate.status_code == 409

    _cleanup(employee_ids=[first.json()["id"]])


# ---------------------------------------------------------------------
# The org-chart derivation
# ---------------------------------------------------------------------


def test_manager_id_is_derived_to_the_ceo_when_created_with_no_team() -> None:
    ceo_id = _ceo_id()
    created = client.post("/employees", json=_valid_create_body(), headers=_admin_headers()).json()

    assert created["team_id"] is None
    assert created["manager_id"] == ceo_id

    _cleanup(employee_ids=[created["id"]])


def test_manager_id_submitted_in_the_request_body_is_not_honored() -> None:
    ceo_id = _ceo_id()
    body = _valid_create_body()
    body["manager_id"] = 999999

    created = client.post("/employees", json=body, headers=_admin_headers()).json()

    assert created["manager_id"] == ceo_id
    assert created["manager_id"] != 999999

    _cleanup(employee_ids=[created["id"]])


# ---------------------------------------------------------------------
# Update: self / manager / Admin
# ---------------------------------------------------------------------


def test_put_self_can_update_first_name_last_name_and_phone() -> None:
    created = client.post("/employees", json=_valid_create_body(), headers=_admin_headers()).json()
    self_headers = _employee_headers(created["email"])

    response = client.put(
        f"/employees/{created['id']}",
        json={"first_name": "Updated", "last_name": "Name", "phone": "555-0000"},
        headers=self_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Updated"
    assert body["last_name"] == "Name"
    assert body["phone"] == "555-0000"

    _cleanup(employee_ids=[created["id"]])


def test_put_someone_else_returns_403() -> None:
    employee_a = client.post("/employees", json=_valid_create_body(), headers=_admin_headers()).json()
    employee_b = client.post("/employees", json=_valid_create_body(), headers=_admin_headers()).json()
    a_headers = _employee_headers(employee_a["email"])

    response = client.put(f"/employees/{employee_b['id']}", json={"first_name": "Hacked"}, headers=a_headers)

    assert response.status_code == 403

    _cleanup(employee_ids=[employee_a["id"], employee_b["id"]])


def test_put_self_phone_whitespace_only_stores_as_null_not_empty_string() -> None:
    created = client.post("/employees", json=_valid_create_body(phone="555-1234"), headers=_admin_headers()).json()
    assert created["phone"] == "555-1234"
    self_headers = _employee_headers(created["email"])

    response = client.put(f"/employees/{created['id']}", json={"phone": "   "}, headers=self_headers)

    assert response.status_code == 200
    assert response.json()["phone"] is None

    _cleanup(employee_ids=[created["id"]])


def test_self_cannot_edit_work_location_id() -> None:
    """The new manager/Admin-only field family (slice 5) - self is not
    in the allowed set, and must be REJECTED (403), not silently
    dropped: a silently-dropped field returns 200 and leaves the caller
    believing the change saved.
    """
    created = client.post("/employees", json=_valid_create_body(), headers=_admin_headers()).json()
    self_headers = _employee_headers(created["email"])

    response = client.put(
        f"/employees/{created['id']}", json={"work_location_id": created["work_location_id"]}, headers=self_headers
    )

    assert response.status_code == 403

    _cleanup(employee_ids=[created["id"]])


# ---------------------------------------------------------------------
# Get by id
# ---------------------------------------------------------------------


def test_get_unknown_employee_returns_410() -> None:
    response = client.get("/employees/999999", headers=_ceo_headers())
    assert response.status_code == 410


# ---------------------------------------------------------------------
# Delete guards
# ---------------------------------------------------------------------


def test_delete_the_ceo_is_blocked() -> None:
    ceo_id = _ceo_id()
    response = client.delete(f"/employees/{ceo_id}", headers=_admin_headers())
    assert response.status_code == 409

    still_active = client.get(f"/employees/{ceo_id}", headers=_admin_headers())
    assert still_active.json()["is_active"] is True


def test_delete_the_last_active_admin_is_blocked() -> None:
    """At least one active Admin must remain. DELETE requires the ADMIN
    role, so the only reachable case is the last Admin deleting
    themselves - reaching "exactly one active Admin" needs the seeded
    Admin temporarily deactivated via direct SQL (no way to do that
    through the API without tripping this very guard), restored either
    way in a finally block.
    """
    lone_admin = client.post("/employees", json=_valid_create_body(role="ADMIN"), headers=_admin_headers()).json()

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE employees SET is_active = false WHERE email = %s", (_ADMIN_EMAIL,))

        lone_admin_headers = _employee_headers(lone_admin["email"])
        response = client.delete(f"/employees/{lone_admin['id']}", headers=lone_admin_headers)
        assert response.status_code == 409
    finally:
        with conn.cursor() as cur:
            cur.execute("UPDATE employees SET is_active = true WHERE email = %s", (_ADMIN_EMAIL,))

    _cleanup(employee_ids=[lone_admin["id"]])


def test_delete_blocked_by_active_direct_reports() -> None:
    """A manager can't be deactivated while someone's manager_id still
    points at them - that would leave a report pointing at an inactive
    person, a broken org chart, visible in the demo. Real teams exist
    now, so this needs no raw-SQL setup - a manager with one active team
    member has exactly that.
    """
    fixture = _make_manager_with_team(member_count=1)
    manager = fixture["manager"]

    response = client.delete(f"/employees/{manager['id']}", headers=_admin_headers())
    assert response.status_code == 409

    still_active = client.get(f"/employees/{manager['id']}", headers=_admin_headers())
    assert still_active.json()["is_active"] is True

    _cleanup(
        employee_ids=[manager["id"], fixture["members"][0]["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_deactivating_a_manager_with_an_otherwise_empty_team_also_deactivates_the_team() -> None:
    """The slice 5 cascade: once a manager has no active reports (their
    team is otherwise empty), deactivating them must ALSO deactivate
    their team in the same transaction - teams.manager_id is NOT NULL
    and can't be left pointing at an inactive person.
    """
    fixture = _make_manager_with_team()
    manager = fixture["manager"]

    response = client.delete(f"/employees/{manager['id']}", headers=_admin_headers())
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    team = client.get(f"/teams/{fixture['team']['id']}", headers=_admin_headers())
    assert team.json()["is_active"] is False

    _cleanup(employee_ids=[manager["id"]], team_ids=[fixture["team"]["id"]], department_ids=[fixture["department"]["id"]])


# ---------------------------------------------------------------------
# The demotion guard (dormant since slice 4, reachable now - debt 6c)
# ---------------------------------------------------------------------


def test_role_change_away_from_manager_blocked_while_managing_an_active_team() -> None:
    """Slice 4 wrote this guard dormant (no teams existed to trip it).
    Slice 5 makes role MANAGER exist only while its holder manages an
    active team, so this now always fires for a current MANAGER -
    direct demotion, like direct promotion, doesn't exist; both fall out
    of team operations only (PUT /teams replacement, or DELETE /teams /
    DELETE /employees on the manager).
    """
    fixture = _make_manager_with_team()
    manager = fixture["manager"]

    response = client.put(f"/employees/{manager['id']}", json={"role": "EMPLOYEE"}, headers=_admin_headers())
    assert response.status_code == 409

    _cleanup(employee_ids=[manager["id"]], team_ids=[fixture["team"]["id"]], department_ids=[fixture["department"]["id"]])


# ---------------------------------------------------------------------
# The Manager half of the permission model (slice 5 section 4)
# ---------------------------------------------------------------------


def test_manager_edits_own_team_members_phone() -> None:
    fixture = _make_manager_with_team(member_count=1)
    manager, member = fixture["manager"], fixture["members"][0]
    manager_headers = _employee_headers(manager["email"])

    response = client.put(f"/employees/{member['id']}", json={"phone": "555-9999"}, headers=manager_headers)

    assert response.status_code == 200
    assert response.json()["phone"] == "555-9999"

    _cleanup(
        employee_ids=[manager["id"], member["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_manager_edits_own_team_members_work_location_availability_expertise() -> None:
    fixture = _make_manager_with_team(member_count=1)
    manager, member = fixture["manager"], fixture["members"][0]
    manager_headers = _employee_headers(manager["email"])

    response = client.put(
        f"/employees/{member['id']}",
        json={
            "work_location_id": member["work_location_id"],
            "project_availability": not member["project_availability"],
            "expertise_id": member["expertise_id"],
        },
        headers=manager_headers,
    )

    assert response.status_code == 200
    assert response.json()["project_availability"] == (not member["project_availability"])

    _cleanup(
        employee_ids=[manager["id"], member["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_manager_cannot_edit_someone_on_a_different_team() -> None:
    fixture_a = _make_manager_with_team()
    fixture_b = _make_manager_with_team(member_count=1)
    manager_a_headers = _employee_headers(fixture_a["manager"]["email"])
    other_teams_member = fixture_b["members"][0]

    response = client.put(
        f"/employees/{other_teams_member['id']}", json={"phone": "555-0000"}, headers=manager_a_headers
    )

    assert response.status_code == 403

    _cleanup(
        employee_ids=[fixture_a["manager"]["id"], fixture_b["manager"]["id"], other_teams_member["id"]],
        team_ids=[fixture_a["team"]["id"], fixture_b["team"]["id"]],
        department_ids=[fixture_a["department"]["id"], fixture_b["department"]["id"]],
    )


def test_manager_cannot_change_role() -> None:
    fixture = _make_manager_with_team(member_count=1)
    manager, member = fixture["manager"], fixture["members"][0]
    manager_headers = _employee_headers(manager["email"])

    response = client.put(f"/employees/{member['id']}", json={"role": "ADMIN"}, headers=manager_headers)

    assert response.status_code == 403

    _cleanup(
        employee_ids=[manager["id"], member["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_manager_releases_a_team_member_to_the_pool() -> None:
    fixture = _make_manager_with_team(member_count=1)
    manager, member = fixture["manager"], fixture["members"][0]
    ceo_id = _ceo_id()
    manager_headers = _employee_headers(manager["email"])

    response = client.put(f"/employees/{member['id']}", json={"team_id": None}, headers=manager_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["team_id"] is None
    assert body["manager_id"] == ceo_id

    _cleanup(
        employee_ids=[manager["id"], member["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_manager_cannot_change_their_own_team_id() -> None:
    """The LOCK: team_id can't be changed for anyone who manages a team
    - not by that manager either. The only path is PUT /teams.
    """
    fixture = _make_manager_with_team()
    manager = fixture["manager"]
    manager_headers = _employee_headers(manager["email"])

    response = client.put(f"/employees/{manager['id']}", json={"team_id": None}, headers=manager_headers)

    assert response.status_code == 409

    _cleanup(employee_ids=[manager["id"]], team_ids=[fixture["team"]["id"]], department_ids=[fixture["department"]["id"]])


def test_admin_cannot_change_a_team_managers_team_id() -> None:
    """Same LOCK, and it applies to Admin too - authorized in general to
    touch team_id, still blocked by the state invariant.
    """
    fixture = _make_manager_with_team()
    manager = fixture["manager"]

    response = client.put(f"/employees/{manager['id']}", json={"team_id": None}, headers=_admin_headers())

    assert response.status_code == 409

    _cleanup(employee_ids=[manager["id"]], team_ids=[fixture["team"]["id"]], department_ids=[fixture["department"]["id"]])


def test_admin_places_an_employee_into_a_team() -> None:
    """"Only Admin places people" - the positive case."""
    fixture = _make_manager_with_team()
    pool_employee = client.post("/employees", json=_valid_create_body(), headers=_admin_headers()).json()

    response = client.put(
        f"/employees/{pool_employee['id']}", json={"team_id": fixture["team"]["id"]}, headers=_admin_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["team_id"] == fixture["team"]["id"]
    assert body["manager_id"] == fixture["manager"]["id"]

    _cleanup(
        employee_ids=[fixture["manager"]["id"], pool_employee["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_admin_placing_into_an_inactive_team_returns_422_naming_the_field() -> None:
    """A plain FK can't catch "exists but soft-deleted" - needs the
    explicit check. Same reasoning, and same status code, as the
    inactive-department checks in team_repository.
    """
    fixture = _make_manager_with_team()
    deleted = client.delete(f"/teams/{fixture['team']['id']}", headers=_ceo_headers())
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False

    pool_employee = client.post("/employees", json=_valid_create_body(), headers=_admin_headers()).json()
    response = client.put(
        f"/employees/{pool_employee['id']}", json={"team_id": fixture["team"]["id"]}, headers=_admin_headers()
    )

    assert response.status_code == 422
    assert response.json()["field"] == "team_id"

    _cleanup(
        employee_ids=[fixture["manager"]["id"], pool_employee["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


# ---------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------


def test_list_filters_by_q() -> None:
    unique_first_name = f"Findable{uuid.uuid4().hex[:8]}"
    created = client.post("/employees", json=_valid_create_body(first_name=unique_first_name), headers=_admin_headers()).json()

    response = client.get(f"/employees?q={unique_first_name}", headers=_admin_headers())
    assert response.status_code == 200
    assert any(e["id"] == created["id"] for e in response.json())

    _cleanup(employee_ids=[created["id"]])


def test_list_filters_by_expertise_id() -> None:
    frontend_id = next(v["id"] for v in client.get("/expertise", headers=_admin_headers()).json() if v["name"] == "Frontend")
    created = client.post("/employees", json=_valid_create_body(expertise_id=frontend_id), headers=_admin_headers()).json()

    response = client.get(f"/employees?expertise_id={frontend_id}", headers=_admin_headers())
    assert response.status_code == 200
    assert any(e["id"] == created["id"] for e in response.json())

    _cleanup(employee_ids=[created["id"]])


def test_list_filters_by_available() -> None:
    created = client.post("/employees", json=_valid_create_body(project_availability=False), headers=_admin_headers()).json()

    unavailable = client.get("/employees?available=false", headers=_admin_headers())
    assert unavailable.status_code == 200
    assert any(e["id"] == created["id"] for e in unavailable.json())

    available_only = client.get("/employees?available=true", headers=_admin_headers())
    assert not any(e["id"] == created["id"] for e in available_only.json())

    _cleanup(employee_ids=[created["id"]])


def test_list_filters_by_team_id() -> None:
    """Debt from slice 4: built correctly, only the empty case was
    testable (no teams existed). Real teams exist now.
    """
    fixture = _make_manager_with_team(member_count=1)

    response = client.get(f"/employees?team_id={fixture['team']['id']}", headers=_admin_headers())

    assert response.status_code == 200
    ids = {e["id"] for e in response.json()}
    assert fixture["manager"]["id"] in ids
    assert fixture["members"][0]["id"] in ids

    _cleanup(
        employee_ids=[fixture["manager"]["id"], fixture["members"][0]["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_list_filters_by_department_id() -> None:
    """Same debt as team_id above - filters through teams, untestable
    until teams existed.
    """
    fixture = _make_manager_with_team()

    response = client.get(f"/employees?department_id={fixture['department']['id']}", headers=_admin_headers())

    assert response.status_code == 200
    assert fixture["manager"]["id"] in {e["id"] for e in response.json()}

    _cleanup(employee_ids=[fixture["manager"]["id"]], team_ids=[fixture["team"]["id"]], department_ids=[fixture["department"]["id"]])
