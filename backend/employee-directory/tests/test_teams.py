"""Tests for /teams: atomic creation, manager replacement, and the two
ways a team ends (DELETE /teams, and DELETE /employees on its manager —
that cascade is covered in test_employees.py, alongside the manager
permission model, since it's PUT /employees under test there).
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


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:10]}@example.com"


def _make_employee(**overrides) -> dict:
    admin_headers = _admin_headers()
    locations = client.get("/work-locations", headers=admin_headers).json()
    expertise_values = client.get("/expertise", headers=admin_headers).json()
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
    response = client.post("/employees", json=body, headers=admin_headers)
    assert response.status_code == 201, response.text
    return response.json()


def _make_department(**overrides) -> dict:
    body = {"name": f"Dept {uuid.uuid4().hex[:8]}"}
    body.update(overrides)
    response = client.post("/departments", json=body, headers=_ceo_headers())
    assert response.status_code == 201, response.text
    return response.json()


def _cleanup(*, employee_ids=(), team_ids=(), department_ids=()) -> None:
    conn = db.get_connection()
    hard_delete_teams(conn, list(team_ids))
    hard_delete_employees(conn, list(employee_ids))
    hard_delete_departments(conn, list(department_ids))


# ---------------------------------------------------------------------
# POST /teams
# ---------------------------------------------------------------------


def test_ceo_creates_a_team_and_the_nominee_is_promoted() -> None:
    department = _make_department()
    nominee = _make_employee()

    response = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    )

    assert response.status_code == 201
    team = response.json()
    assert team["manager_id"] == nominee["id"]
    assert team["department_id"] == department["id"]

    promoted = client.get(f"/employees/{nominee['id']}", headers=_admin_headers()).json()
    assert promoted["role"] == "MANAGER"
    assert promoted["team_id"] == team["id"]
    assert promoted["manager_id"] == client.get("/me", headers=_ceo_headers()).json()["id"]

    _cleanup(employee_ids=[nominee["id"]], team_ids=[team["id"]], department_ids=[department["id"]])


def test_post_teams_requires_ceo_role() -> None:
    department = _make_department()
    nominee = _make_employee()

    response = client.post(
        "/teams",
        json={"name": "irrelevant", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_admin_headers(),
    )

    assert response.status_code == 403

    _cleanup(employee_ids=[nominee["id"]], department_ids=[department["id"]])


def test_post_teams_requires_authentication() -> None:
    response = client.post("/teams", json={"name": "irrelevant", "department_id": 1, "manager_id": 1})
    assert response.status_code == 401


def test_post_teams_nominating_admin_rejected() -> None:
    department = _make_department()

    response = client.post(
        "/teams",
        json={"name": "irrelevant", "department_id": department["id"], "manager_id": 2},  # seeded admin
        headers=_ceo_headers(),
    )

    assert response.status_code == 409
    still_admin = client.get("/employees/2", headers=_admin_headers())
    assert still_admin.json()["role"] == "ADMIN"

    _cleanup(department_ids=[department["id"]])


def test_post_teams_nominating_ceo_rejected() -> None:
    department = _make_department()
    ceo_id = client.get("/me", headers=_ceo_headers()).json()["id"]

    response = client.post(
        "/teams",
        json={"name": "irrelevant", "department_id": department["id"], "manager_id": ceo_id},
        headers=_ceo_headers(),
    )

    assert response.status_code == 409

    _cleanup(department_ids=[department["id"]])


def test_post_teams_naming_someone_on_a_different_team_rejected() -> None:
    department_a = _make_department()
    department_b = _make_department()
    nominee_a = _make_employee()
    team_a = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department_a["id"], "manager_id": nominee_a["id"]},
        headers=_ceo_headers(),
    ).json()

    response = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department_b["id"], "manager_id": nominee_a["id"]},
        headers=_ceo_headers(),
    )

    assert response.status_code == 409

    _cleanup(
        employee_ids=[nominee_a["id"]],
        team_ids=[team_a["id"]],
        department_ids=[department_a["id"], department_b["id"]],
    )


def test_post_teams_into_inactive_department_rejected() -> None:
    department = _make_department()
    deleted = client.delete(f"/departments/{department['id']}", headers=_ceo_headers())
    assert deleted.status_code == 200
    nominee = _make_employee()

    response = client.post(
        "/teams",
        json={"name": "irrelevant", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    )

    assert response.status_code == 422
    assert response.json()["field"] == "department_id"

    _cleanup(employee_ids=[nominee["id"]], department_ids=[department["id"]])


def test_post_employees_with_role_manager_rejected() -> None:
    """Section 0: MANAGER is never pre-set on create — pinned here too,
    alongside the team tests, since it's what makes a MANAGER without a
    team structurally impossible.
    """
    response = client.post(
        "/employees",
        json={
            "first_name": "Test",
            "last_name": "Manager",
            "email": _unique_email(),
            "password": _TEST_PASSWORD,
            "role": "MANAGER",
            "work_location_id": 1,
            "expertise_id": 1,
        },
        headers=_admin_headers(),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------
# PUT /teams — manager replacement
# ---------------------------------------------------------------------


def test_put_replaces_the_manager_and_repoints_every_member() -> None:
    department = _make_department()
    nominee = _make_employee()
    incoming = _make_employee()
    bystander = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()
    client.put(f"/employees/{bystander['id']}", json={"team_id": team["id"]}, headers=_admin_headers())

    response = client.put(f"/teams/{team['id']}", json={"manager_id": incoming["id"]}, headers=_ceo_headers())

    assert response.status_code == 200
    assert response.json()["manager_id"] == incoming["id"]

    promoted = client.get(f"/employees/{incoming['id']}", headers=_admin_headers()).json()
    assert promoted["role"] == "MANAGER"
    assert promoted["team_id"] == team["id"]

    demoted = client.get(f"/employees/{nominee['id']}", headers=_admin_headers()).json()
    assert demoted["role"] == "EMPLOYEE"
    assert demoted["team_id"] == team["id"]  # still on the team, as an IC
    assert demoted["manager_id"] == incoming["id"]

    bystander_after = client.get(f"/employees/{bystander['id']}", headers=_admin_headers()).json()
    assert bystander_after["manager_id"] == incoming["id"]

    _cleanup(
        employee_ids=[nominee["id"], incoming["id"], bystander["id"]],
        team_ids=[team["id"]],
        department_ids=[department["id"]],
    )


def test_put_replacement_incoming_from_the_pool_gets_team_id_set() -> None:
    department = _make_department()
    nominee = _make_employee()
    incoming = _make_employee()  # never on any team — the pool
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()
    assert incoming["team_id"] is None

    response = client.put(f"/teams/{team['id']}", json={"manager_id": incoming["id"]}, headers=_ceo_headers())

    assert response.status_code == 200
    promoted = client.get(f"/employees/{incoming['id']}", headers=_admin_headers()).json()
    assert promoted["team_id"] == team["id"]

    _cleanup(employee_ids=[nominee["id"], incoming["id"]], team_ids=[team["id"]], department_ids=[department["id"]])


def test_put_nominating_admin_or_ceo_rejected() -> None:
    department = _make_department()
    nominee = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()
    ceo_id = client.get("/me", headers=_ceo_headers()).json()["id"]

    admin_response = client.put(f"/teams/{team['id']}", json={"manager_id": 2}, headers=_ceo_headers())
    ceo_response = client.put(f"/teams/{team['id']}", json={"manager_id": ceo_id}, headers=_ceo_headers())

    assert admin_response.status_code == 409
    assert ceo_response.status_code == 409

    _cleanup(employee_ids=[nominee["id"]], team_ids=[team["id"]], department_ids=[department["id"]])


def test_put_naming_someone_who_already_manages_another_active_team_returns_409() -> None:
    department = _make_department()
    nominee_a = _make_employee()
    nominee_b = _make_employee()
    team_a = client.post(
        "/teams",
        json={"name": f"Team A {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee_a["id"]},
        headers=_ceo_headers(),
    ).json()
    team_b = client.post(
        "/teams",
        json={"name": f"Team B {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee_b["id"]},
        headers=_ceo_headers(),
    ).json()

    response = client.put(f"/teams/{team_a['id']}", json={"manager_id": nominee_b["id"]}, headers=_ceo_headers())

    assert response.status_code == 409

    _cleanup(
        employee_ids=[nominee_a["id"], nominee_b["id"]],
        team_ids=[team_a["id"], team_b["id"]],
        department_ids=[department["id"]],
    )


def test_put_naming_the_current_manager_is_a_noop() -> None:
    department = _make_department()
    nominee = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()
    ceo_id = client.get("/me", headers=_ceo_headers()).json()["id"]

    response = client.put(f"/teams/{team['id']}", json={"manager_id": nominee["id"]}, headers=_ceo_headers())

    assert response.status_code == 200
    still_manager = client.get(f"/employees/{nominee['id']}", headers=_admin_headers()).json()
    assert still_manager["role"] == "MANAGER"
    assert still_manager["manager_id"] == ceo_id  # not themselves — the bug this guards against

    _cleanup(employee_ids=[nominee["id"]], team_ids=[team["id"]], department_ids=[department["id"]])


def test_put_moving_a_team_to_an_inactive_department_rejected() -> None:
    department = _make_department()
    other_department = _make_department()
    client.delete(f"/departments/{other_department['id']}", headers=_ceo_headers())
    nominee = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()

    response = client.put(f"/teams/{team['id']}", json={"department_id": other_department["id"]}, headers=_ceo_headers())

    assert response.status_code == 422
    assert response.json()["field"] == "department_id"

    _cleanup(
        employee_ids=[nominee["id"]],
        team_ids=[team["id"]],
        department_ids=[department["id"], other_department["id"]],
    )


# ---------------------------------------------------------------------
# GET /teams/{id}
# ---------------------------------------------------------------------


def test_get_unknown_team_returns_410() -> None:
    response = client.get("/teams/999999", headers=_ceo_headers())
    assert response.status_code == 410


def test_get_team_returns_an_inactive_team() -> None:
    """410 means unknown id only, never "found but inactive" — matches
    department/employee get-by-id.
    """
    department = _make_department()
    nominee = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()
    client.delete(f"/teams/{team['id']}", headers=_ceo_headers())

    response = client.get(f"/teams/{team['id']}", headers=_ceo_headers())

    assert response.status_code == 200
    assert response.json()["is_active"] is False

    _cleanup(employee_ids=[nominee["id"]], team_ids=[team["id"]], department_ids=[department["id"]])


# ---------------------------------------------------------------------
# DELETE /teams
# ---------------------------------------------------------------------


def test_delete_team_blocked_by_an_active_non_manager_member() -> None:
    department = _make_department()
    nominee = _make_employee()
    member = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()
    client.put(f"/employees/{member['id']}", json={"team_id": team["id"]}, headers=_admin_headers())

    response = client.delete(f"/teams/{team['id']}", headers=_ceo_headers())

    assert response.status_code == 409

    _cleanup(
        employee_ids=[nominee["id"], member["id"]],
        team_ids=[team["id"]],
        department_ids=[department["id"]],
    )


def test_delete_team_with_only_the_manager_pools_them_correctly() -> None:
    department = _make_department()
    nominee = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()
    ceo_id = client.get("/me", headers=_ceo_headers()).json()["id"]

    response = client.delete(f"/teams/{team['id']}", headers=_ceo_headers())

    assert response.status_code == 200
    assert response.json()["is_active"] is False

    pooled = client.get(f"/employees/{nominee['id']}", headers=_admin_headers()).json()
    assert pooled["role"] == "EMPLOYEE"
    assert pooled["team_id"] is None
    assert pooled["manager_id"] == ceo_id

    _cleanup(employee_ids=[nominee["id"]], team_ids=[team["id"]], department_ids=[department["id"]])


def test_delete_team_is_idempotent() -> None:
    department = _make_department()
    nominee = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()

    first = client.delete(f"/teams/{team['id']}", headers=_ceo_headers())
    second = client.delete(f"/teams/{team['id']}", headers=_ceo_headers())

    assert first.status_code == 200
    assert second.status_code == 200

    _cleanup(employee_ids=[nominee["id"]], team_ids=[team["id"]], department_ids=[department["id"]])


def test_delete_teams_requires_ceo_role() -> None:
    response = client.delete("/teams/999999", headers=_admin_headers())
    assert response.status_code == 403


def test_teams_write_requires_authentication() -> None:
    assert client.post("/teams", json={"name": "x", "department_id": 1, "manager_id": 1}).status_code == 401
    assert client.put("/teams/999999", json={"name": "x"}).status_code == 401
    assert client.delete("/teams/999999").status_code == 401


def test_list_and_get_teams_require_authentication() -> None:
    assert client.get("/teams").status_code == 401
    assert client.get("/teams/1").status_code == 401


# ---------------------------------------------------------------------
# Department delete guard, positive case (debt 6a)
# ---------------------------------------------------------------------


def test_department_delete_blocked_by_an_active_team_with_an_active_employee() -> None:
    """Slice 3 wrote this guard against departments -> teams ->
    employees and noted the rejection case couldn't be tested until
    teams existed. It exists now: a department with an active team
    containing an active employee (the manager alone is enough — they
    count as a member) returns 409 on DELETE.
    """
    department = _make_department()
    nominee = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()

    response = client.delete(f"/departments/{department['id']}", headers=_ceo_headers())

    assert response.status_code == 409

    _cleanup(employee_ids=[nominee["id"]], team_ids=[team["id"]], department_ids=[department["id"]])
