"""Tests for skills: the shared lookup list, get-or-create with the
insert race handled, attach/detach idempotency, the manager/self/Admin
authorization split, and the deferred skill_id employee filter.
"""

import uuid

from fastapi.testclient import TestClient

import app.repositories.db as db
import app.repositories.skill_repository as skill_repo
from app.main import app
from conftest import hard_delete_departments, hard_delete_employees, hard_delete_skills, hard_delete_teams

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


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:10]}@example.com"


def _unique_skill_name() -> str:
    return f"Skill {uuid.uuid4().hex[:8]}"


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


def _make_department_and_team() -> dict:
    """A department + a team + its manager, via POST /teams (same
    fixture shape test_employees.py/test_teams.py already use)."""
    department = client.post(
        "/departments", json={"name": f"Dept {uuid.uuid4().hex[:8]}"}, headers=_ceo_headers()
    ).json()
    nominee = _make_employee()
    team = client.post(
        "/teams",
        json={"name": f"Team {uuid.uuid4().hex[:8]}", "department_id": department["id"], "manager_id": nominee["id"]},
        headers=_ceo_headers(),
    ).json()
    manager = client.get(f"/employees/{nominee['id']}", headers=_admin_headers()).json()
    return {"department": department, "team": team, "manager": manager}


def _cleanup(*, employee_ids=(), team_ids=(), department_ids=(), skill_ids=()) -> None:
    conn = db.get_connection()
    hard_delete_skills(conn, list(skill_ids))
    hard_delete_teams(conn, list(team_ids))
    hard_delete_employees(conn, list(employee_ids))
    hard_delete_departments(conn, list(department_ids))


# ---------------------------------------------------------------------
# GET /skills
# ---------------------------------------------------------------------


def test_list_skills_includes_a_newly_created_one() -> None:
    name = _unique_skill_name()
    employee = _make_employee()
    attach = client.post(f"/employees/{employee['id']}/skills", json={"name": name}, headers=_admin_headers())
    assert attach.status_code == 201
    skill_id = attach.json()[0]["id"]

    response = client.get("/skills", headers=_admin_headers())

    assert response.status_code == 200
    assert any(s["id"] == skill_id and s["name"] == name for s in response.json())

    _cleanup(employee_ids=[employee["id"]], skill_ids=[skill_id])


def test_list_skills_requires_authentication() -> None:
    assert client.get("/skills").status_code == 401


# ---------------------------------------------------------------------
# GET /employees/{id}/skills
# ---------------------------------------------------------------------


def test_get_employee_skills_unknown_employee_returns_410() -> None:
    response = client.get("/employees/999999/skills", headers=_admin_headers())
    assert response.status_code == 410


def test_get_employee_skills_requires_authentication() -> None:
    assert client.get("/employees/1/skills").status_code == 401


# ---------------------------------------------------------------------
# POST /employees/{id}/skills — get-or-create + attach
# ---------------------------------------------------------------------


def test_attach_by_name_skill_does_not_exist_yet_creates_and_attaches() -> None:
    employee = _make_employee()
    name = _unique_skill_name()

    response = client.post(f"/employees/{employee['id']}/skills", json={"name": name}, headers=_admin_headers())

    assert response.status_code == 201
    skills = response.json()
    assert any(s["name"] == name for s in skills)
    skill_id = next(s["id"] for s in skills if s["name"] == name)

    _cleanup(employee_ids=[employee["id"]], skill_ids=[skill_id])


def test_attach_by_name_case_variant_reuses_the_same_row_not_a_duplicate() -> None:
    employee_a = _make_employee()
    employee_b = _make_employee()
    name = _unique_skill_name()

    first = client.post(f"/employees/{employee_a['id']}/skills", json={"name": name}, headers=_admin_headers())
    assert first.status_code == 201
    skill_id = first.json()[0]["id"]

    second = client.post(
        f"/employees/{employee_b['id']}/skills", json={"name": name.upper()}, headers=_admin_headers()
    )
    assert second.status_code == 201
    assert second.json()[0]["id"] == skill_id  # same row, not a new one

    all_skills = client.get("/skills", headers=_admin_headers()).json()
    assert sum(1 for s in all_skills if s["id"] == skill_id) == 1

    _cleanup(employee_ids=[employee_a["id"], employee_b["id"]], skill_ids=[skill_id])


def test_attach_a_skill_the_employee_already_has_is_a_noop() -> None:
    employee = _make_employee()
    name = _unique_skill_name()
    first = client.post(f"/employees/{employee['id']}/skills", json={"name": name}, headers=_admin_headers())
    assert first.status_code == 201
    skill_id = first.json()[0]["id"]

    second = client.post(f"/employees/{employee['id']}/skills", json={"name": name}, headers=_admin_headers())

    assert second.status_code == 200
    assert len([s for s in second.json() if s["id"] == skill_id]) == 1

    conn = db.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM employee_skills WHERE employee_id = %s AND skill_id = %s",
            (employee["id"], skill_id),
        )
        assert cur.fetchone()[0] == 1

    _cleanup(employee_ids=[employee["id"]], skill_ids=[skill_id])


def test_attach_empty_name_returns_422() -> None:
    employee = _make_employee()
    response = client.post(f"/employees/{employee['id']}/skills", json={"name": ""}, headers=_admin_headers())
    assert response.status_code == 422
    _cleanup(employee_ids=[employee["id"]])


def test_attach_whitespace_only_name_returns_422() -> None:
    employee = _make_employee()
    response = client.post(f"/employees/{employee['id']}/skills", json={"name": "   "}, headers=_admin_headers())
    assert response.status_code == 422
    _cleanup(employee_ids=[employee["id"]])


def test_attach_name_over_max_length_returns_422() -> None:
    employee = _make_employee()
    response = client.post(
        f"/employees/{employee['id']}/skills", json={"name": "x" * 256}, headers=_admin_headers()
    )
    assert response.status_code == 422
    _cleanup(employee_ids=[employee["id"]])


def test_attach_requires_authentication() -> None:
    response = client.post("/employees/1/skills", json={"name": "irrelevant"})
    assert response.status_code == 401


def test_attach_to_an_inactive_employee_returns_409() -> None:
    """Creates a new row (unlike editing an existing field), so this is
    guarded even though PUT /employees isn't — see skill_service.
    """
    employee = _make_employee()
    deactivated = client.delete(f"/employees/{employee['id']}", headers=_admin_headers())
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    response = client.post(
        f"/employees/{employee['id']}/skills", json={"name": _unique_skill_name()}, headers=_admin_headers()
    )

    assert response.status_code == 409
    assert "inactive" in response.json()["detail"].lower()

    _cleanup(employee_ids=[employee["id"]])


# ---------------------------------------------------------------------
# DELETE /employees/{id}/skills/{skill_id}
# ---------------------------------------------------------------------


def test_detach_a_skill_the_employee_does_not_have_is_a_clean_success() -> None:
    employee = _make_employee()

    response = client.delete(f"/employees/{employee['id']}/skills/999999", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json() == []

    _cleanup(employee_ids=[employee["id"]])


def test_detach_removes_the_skill() -> None:
    employee = _make_employee()
    name = _unique_skill_name()
    attach = client.post(f"/employees/{employee['id']}/skills", json={"name": name}, headers=_admin_headers())
    skill_id = attach.json()[0]["id"]

    response = client.delete(f"/employees/{employee['id']}/skills/{skill_id}", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json() == []

    _cleanup(employee_ids=[employee["id"]], skill_ids=[skill_id])


def test_detach_from_an_inactive_employee_still_works() -> None:
    """No is_active guard on detach — unlike attach, removing data from
    an inactive record is never harmful (see skill_service).
    """
    employee = _make_employee()
    name = _unique_skill_name()
    attach = client.post(f"/employees/{employee['id']}/skills", json={"name": name}, headers=_admin_headers())
    skill_id = attach.json()[0]["id"]
    client.delete(f"/employees/{employee['id']}", headers=_admin_headers())

    response = client.delete(f"/employees/{employee['id']}/skills/{skill_id}", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json() == []

    _cleanup(employee_ids=[employee["id"]], skill_ids=[skill_id])


def test_detach_requires_authentication() -> None:
    assert client.delete("/employees/1/skills/1").status_code == 401


# ---------------------------------------------------------------------
# Authorization: self / manager-of-team / Admin, not CEO
# ---------------------------------------------------------------------


def test_self_attaches_own_skill() -> None:
    employee = _make_employee()
    self_headers = _employee_headers(employee["email"])
    name = _unique_skill_name()

    response = client.post(f"/employees/{employee['id']}/skills", json={"name": name}, headers=self_headers)

    assert response.status_code == 201
    skill_id = response.json()[0]["id"]

    _cleanup(employee_ids=[employee["id"]], skill_ids=[skill_id])


def test_manager_attaches_skill_for_own_team_member() -> None:
    fixture = _make_department_and_team()
    manager = fixture["manager"]
    member = _make_employee()
    client.put(f"/employees/{member['id']}", json={"team_id": fixture["team"]["id"]}, headers=_admin_headers())
    manager_headers = _employee_headers(manager["email"])
    name = _unique_skill_name()

    response = client.post(f"/employees/{member['id']}/skills", json={"name": name}, headers=manager_headers)

    assert response.status_code == 201
    skill_id = response.json()[0]["id"]

    _cleanup(
        employee_ids=[manager["id"], member["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
        skill_ids=[skill_id],
    )


def test_manager_attempts_on_someone_not_on_their_team_returns_403() -> None:
    fixture = _make_department_and_team()
    manager_headers = _employee_headers(fixture["manager"]["email"])
    other_employee = _make_employee()

    response = client.post(
        f"/employees/{other_employee['id']}/skills", json={"name": _unique_skill_name()}, headers=manager_headers
    )

    assert response.status_code == 403

    _cleanup(
        employee_ids=[fixture["manager"]["id"], other_employee["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_admin_attaches_for_any_employee() -> None:
    employee = _make_employee()
    name = _unique_skill_name()

    response = client.post(f"/employees/{employee['id']}/skills", json={"name": name}, headers=_admin_headers())

    assert response.status_code == 201
    skill_id = response.json()[0]["id"]

    _cleanup(employee_ids=[employee["id"]], skill_ids=[skill_id])


def test_ceo_cannot_attach_skill_for_someone_else() -> None:
    """Not CEO - consistent with the CEO having no general
    employee-editing power anywhere in this app.
    """
    employee = _make_employee()

    response = client.post(
        f"/employees/{employee['id']}/skills", json={"name": _unique_skill_name()}, headers=_ceo_headers()
    )

    assert response.status_code == 403

    _cleanup(employee_ids=[employee["id"]])


def test_employee_cannot_attach_skill_for_someone_else() -> None:
    employee_a = _make_employee()
    employee_b = _make_employee()
    a_headers = _employee_headers(employee_a["email"])

    response = client.post(
        f"/employees/{employee_b['id']}/skills", json={"name": _unique_skill_name()}, headers=a_headers
    )

    assert response.status_code == 403

    _cleanup(employee_ids=[employee_a["id"], employee_b["id"]])


# ---------------------------------------------------------------------
# The deferred skill_id employee filter
# ---------------------------------------------------------------------


def test_list_employees_filters_by_skill_id() -> None:
    has_skill = _make_employee()
    lacks_skill = _make_employee()
    name = _unique_skill_name()
    attach = client.post(f"/employees/{has_skill['id']}/skills", json={"name": name}, headers=_admin_headers())
    skill_id = attach.json()[0]["id"]

    response = client.get(f"/employees?skill_id={skill_id}", headers=_admin_headers())

    assert response.status_code == 200
    ids = {e["id"] for e in response.json()}
    assert has_skill["id"] in ids
    assert lacks_skill["id"] not in ids

    _cleanup(employee_ids=[has_skill["id"], lacks_skill["id"]], skill_ids=[skill_id])


# ---------------------------------------------------------------------
# The get-or-create insert race
# ---------------------------------------------------------------------


def test_get_or_create_skill_handles_the_insert_race(monkeypatch) -> None:
    """Simulates the race directly rather than relying on real
    concurrency (this codebase has one shared connection, not one per
    thread, so true concurrent requests aren't reproducible in-process):
    forces the initial SELECT to report nothing found while the skill
    genuinely already exists, so the INSERT hits a real UniqueViolation —
    exactly what the losing side of two containers racing to add the
    same skill would see. Proves the except branch re-selects and
    returns the existing row rather than raising.
    """
    name = _unique_skill_name()
    existing = skill_repo.get_or_create_skill(name)

    original_find = skill_repo._find_skill_by_lower_name
    calls = {"n": 0}

    def find_that_misses_once(conn, lower_name):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return original_find(conn, lower_name)

    monkeypatch.setattr(skill_repo, "_find_skill_by_lower_name", find_that_misses_once)

    result = skill_repo.get_or_create_skill(name)

    assert result.id == existing.id
    assert calls["n"] == 2  # missed once, re-selected once after the UniqueViolation

    _cleanup(skill_ids=[existing.id])
