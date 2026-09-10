"""Tests for projects: explicit create (open to anyone, 409 on
collision) vs. get-or-create via attach (name only, never touches
description), completed_at set/clear/upsert semantics, the manager/self/
Admin authorization split, the deferred project_id employee filter, and
GET /teams/{id}/achievements.
"""

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.repositories.db as db
import app.repositories.project_repository as project_repo
from app.main import app
from conftest import (
    hard_delete_departments,
    hard_delete_employees,
    hard_delete_projects,
    hard_delete_teams,
)

client = TestClient(app)

_CEO_EMAIL = "ceo@example.com"
_CEO_PASSWORD = "Password123!"
_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASSWORD = "Password123!"
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


def _unique_project_name() -> str:
    return f"Project {uuid.uuid4().hex[:8]}"


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


def _cleanup(*, employee_ids=(), team_ids=(), department_ids=(), project_ids=()) -> None:
    conn = db.get_connection()
    hard_delete_projects(conn, list(project_ids))
    hard_delete_teams(conn, list(team_ids))
    hard_delete_employees(conn, list(employee_ids))
    hard_delete_departments(conn, list(department_ids))


# ---------------------------------------------------------------------
# POST /projects — explicit create, open to anyone, 409 on collision
# ---------------------------------------------------------------------


def test_create_project_with_description() -> None:
    name = _unique_project_name()
    response = client.post("/projects", json={"name": name, "description": "A big rewrite"}, headers=_admin_headers())

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == name
    assert body["description"] == "A big rewrite"

    _cleanup(project_ids=[body["id"]])


def test_create_project_open_to_any_authenticated_user() -> None:
    """NOT Admin-gated — deliberately different from PUT."""
    employee = _make_employee()
    self_headers = _employee_headers(employee["email"])

    response = client.post("/projects", json={"name": _unique_project_name()}, headers=self_headers)

    assert response.status_code == 201

    _cleanup(employee_ids=[employee["id"]], project_ids=[response.json()["id"]])


def test_create_project_requires_authentication() -> None:
    response = client.post("/projects", json={"name": "irrelevant"})
    assert response.status_code == 401


def test_create_project_duplicate_name_returns_409() -> None:
    name = _unique_project_name()
    first = client.post("/projects", json={"name": name}, headers=_admin_headers())
    assert first.status_code == 201

    duplicate = client.post("/projects", json={"name": name}, headers=_admin_headers())
    assert duplicate.status_code == 409

    _cleanup(project_ids=[first.json()["id"]])


def test_create_project_duplicate_name_case_variant_returns_409() -> None:
    name = _unique_project_name()
    first = client.post("/projects", json={"name": name}, headers=_admin_headers())
    assert first.status_code == 201

    duplicate = client.post("/projects", json={"name": name.upper()}, headers=_admin_headers())
    assert duplicate.status_code == 409

    _cleanup(project_ids=[first.json()["id"]])


def test_list_projects_requires_authentication() -> None:
    assert client.get("/projects").status_code == 401


def test_get_unknown_project_returns_410() -> None:
    response = client.get("/projects/999999", headers=_admin_headers())
    assert response.status_code == 410


# ---------------------------------------------------------------------
# PUT /projects/{id} — Admin only, load-bearing on POST 409ing
# ---------------------------------------------------------------------


def test_update_project_requires_admin() -> None:
    name = _unique_project_name()
    created = client.post("/projects", json={"name": name}, headers=_admin_headers()).json()

    response = client.put(f"/projects/{created['id']}", json={"description": "hijacked"}, headers=_ceo_headers())

    assert response.status_code == 403

    _cleanup(project_ids=[created["id"]])


def test_update_project_admin_can_rename_and_redescribe() -> None:
    created = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    new_name = _unique_project_name()

    response = client.put(
        f"/projects/{created['id']}", json={"name": new_name, "description": "updated"}, headers=_admin_headers()
    )

    assert response.status_code == 200
    assert response.json()["name"] == new_name
    assert response.json()["description"] == "updated"

    _cleanup(project_ids=[created["id"]])


def test_update_project_name_collision_returns_409() -> None:
    project_a = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    project_b = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()

    response = client.put(f"/projects/{project_a['id']}", json={"name": project_b["name"]}, headers=_admin_headers())

    assert response.status_code == 409

    _cleanup(project_ids=[project_a["id"], project_b["id"]])


# ---------------------------------------------------------------------
# POST /employees/{id}/projects — get-or-create by name, no description
# ---------------------------------------------------------------------


def test_attach_by_name_project_does_not_exist_yet_creates_and_attaches() -> None:
    employee = _make_employee()
    name = _unique_project_name()

    response = client.post(f"/employees/{employee['id']}/projects", json={"name": name}, headers=_admin_headers())

    assert response.status_code == 201
    projects = response.json()
    assert any(p["name"] == name and p["completed_at"] is None for p in projects)
    project_id = next(p["id"] for p in projects if p["name"] == name)

    _cleanup(employee_ids=[employee["id"]], project_ids=[project_id])


def test_attach_by_name_case_variant_reuses_the_same_row() -> None:
    employee_a = _make_employee()
    employee_b = _make_employee()
    name = _unique_project_name()

    first = client.post(f"/employees/{employee_a['id']}/projects", json={"name": name}, headers=_admin_headers())
    assert first.status_code == 201
    project_id = first.json()[0]["id"]

    second = client.post(
        f"/employees/{employee_b['id']}/projects", json={"name": name.upper()}, headers=_admin_headers()
    )
    assert second.status_code == 201
    assert second.json()[0]["id"] == project_id

    _cleanup(employee_ids=[employee_a["id"], employee_b["id"]], project_ids=[project_id])


def test_attach_ignores_a_submitted_description() -> None:
    """ProjectAttach has no description field at all — a caller sneaking
    one into the JSON body is silently ignored by Pydantic (extra
    fields), and the get-or-created project ends up with none.
    """
    employee = _make_employee()
    name = _unique_project_name()

    response = client.post(
        f"/employees/{employee['id']}/projects",
        json={"name": name, "description": "should not stick"},
        headers=_admin_headers(),
    )

    assert response.status_code == 201
    assert response.json()[0]["description"] is None

    _cleanup(employee_ids=[employee["id"]], project_ids=[response.json()[0]["id"]])


def test_attach_a_project_the_employee_already_has_is_a_noop() -> None:
    employee = _make_employee()
    name = _unique_project_name()
    first = client.post(f"/employees/{employee['id']}/projects", json={"name": name}, headers=_admin_headers())
    project_id = first.json()[0]["id"]

    second = client.post(f"/employees/{employee['id']}/projects", json={"name": name}, headers=_admin_headers())

    assert second.status_code == 200
    assert len([p for p in second.json() if p["id"] == project_id]) == 1

    conn = db.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM employee_projects WHERE employee_id = %s AND project_id = %s",
            (employee["id"], project_id),
        )
        assert cur.fetchone()[0] == 1

    _cleanup(employee_ids=[employee["id"]], project_ids=[project_id])


def test_attach_with_completed_at_sets_it_at_creation() -> None:
    employee = _make_employee()
    name = _unique_project_name()
    finished = date.today() - timedelta(days=3)

    response = client.post(
        f"/employees/{employee['id']}/projects",
        json={"name": name, "completed_at": finished.isoformat()},
        headers=_admin_headers(),
    )

    assert response.status_code == 201
    assert response.json()[0]["completed_at"] == finished.isoformat()

    _cleanup(employee_ids=[employee["id"]], project_ids=[response.json()[0]["id"]])


def test_reattach_without_completed_at_does_not_clear_an_existing_completion() -> None:
    """Idempotency: omitting completed_at on a re-attach is UNSET, not
    "clear it" — reopening is PUT's job specifically, which requires the
    field so it can tell "clear" apart from "didn't say."
    """
    employee = _make_employee()
    name = _unique_project_name()
    finished = date.today()
    first = client.post(
        f"/employees/{employee['id']}/projects",
        json={"name": name, "completed_at": finished.isoformat()},
        headers=_admin_headers(),
    )
    project_id = first.json()[0]["id"]

    second = client.post(f"/employees/{employee['id']}/projects", json={"name": name}, headers=_admin_headers())

    assert second.status_code == 200
    assert next(p["completed_at"] for p in second.json() if p["id"] == project_id) == finished.isoformat()

    _cleanup(employee_ids=[employee["id"]], project_ids=[project_id])


def test_attach_empty_name_returns_422() -> None:
    employee = _make_employee()
    response = client.post(f"/employees/{employee['id']}/projects", json={"name": ""}, headers=_admin_headers())
    assert response.status_code == 422
    _cleanup(employee_ids=[employee["id"]])


def test_attach_whitespace_only_name_returns_422() -> None:
    employee = _make_employee()
    response = client.post(f"/employees/{employee['id']}/projects", json={"name": "   "}, headers=_admin_headers())
    assert response.status_code == 422
    _cleanup(employee_ids=[employee["id"]])


def test_attach_name_over_max_length_returns_422() -> None:
    employee = _make_employee()
    response = client.post(
        f"/employees/{employee['id']}/projects", json={"name": "x" * 256}, headers=_admin_headers()
    )
    assert response.status_code == 422
    _cleanup(employee_ids=[employee["id"]])


def test_attach_requires_authentication() -> None:
    response = client.post("/employees/1/projects", json={"name": "irrelevant"})
    assert response.status_code == 401


def test_attach_to_an_inactive_employee_returns_409() -> None:
    employee = _make_employee()
    deactivated = client.delete(f"/employees/{employee['id']}", headers=_admin_headers())
    assert deactivated.status_code == 200

    response = client.post(
        f"/employees/{employee['id']}/projects", json={"name": _unique_project_name()}, headers=_admin_headers()
    )

    assert response.status_code == 409
    assert "inactive" in response.json()["detail"].lower()

    _cleanup(employee_ids=[employee["id"]])


# ---------------------------------------------------------------------
# PUT /employees/{id}/projects/{project_id} — set/clear completed_at
# ---------------------------------------------------------------------


def test_put_completion_sets_completed_at() -> None:
    employee = _make_employee()
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    client.post(f"/employees/{employee['id']}/projects", json={"name": project["name"]}, headers=_admin_headers())
    finished = date.today()

    response = client.put(
        f"/employees/{employee['id']}/projects/{project['id']}",
        json={"completed_at": finished.isoformat()},
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert next(p["completed_at"] for p in response.json() if p["id"] == project["id"]) == finished.isoformat()

    _cleanup(employee_ids=[employee["id"]], project_ids=[project["id"]])


def test_put_completion_clears_completed_at_reopens() -> None:
    employee = _make_employee()
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    client.post(
        f"/employees/{employee['id']}/projects",
        json={"name": project["name"], "completed_at": date.today().isoformat()},
        headers=_admin_headers(),
    )

    response = client.put(
        f"/employees/{employee['id']}/projects/{project['id']}", json={"completed_at": None}, headers=_admin_headers()
    )

    assert response.status_code == 200
    assert next(p["completed_at"] for p in response.json() if p["id"] == project["id"]) is None

    _cleanup(employee_ids=[employee["id"]], project_ids=[project["id"]])


def test_put_completion_upserts_when_not_previously_attached() -> None:
    employee = _make_employee()
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()

    response = client.put(
        f"/employees/{employee['id']}/projects/{project['id']}",
        json={"completed_at": date.today().isoformat()},
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert any(p["id"] == project["id"] for p in response.json())

    _cleanup(employee_ids=[employee["id"]], project_ids=[project["id"]])


def test_put_completion_on_inactive_employee_returns_409() -> None:
    """Guarded the same as attach — this can also create a new row."""
    employee = _make_employee()
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    client.delete(f"/employees/{employee['id']}", headers=_admin_headers())

    response = client.put(
        f"/employees/{employee['id']}/projects/{project['id']}",
        json={"completed_at": date.today().isoformat()},
        headers=_admin_headers(),
    )

    assert response.status_code == 409

    _cleanup(employee_ids=[employee["id"]], project_ids=[project["id"]])


def test_put_completion_requires_authentication() -> None:
    assert client.put("/employees/1/projects/1", json={"completed_at": None}).status_code == 401


def test_put_completion_unknown_project_returns_410() -> None:
    employee = _make_employee()
    response = client.put(
        f"/employees/{employee['id']}/projects/999999", json={"completed_at": None}, headers=_admin_headers()
    )
    assert response.status_code == 410
    _cleanup(employee_ids=[employee["id"]])


# ---------------------------------------------------------------------
# DELETE /employees/{id}/projects/{project_id}
# ---------------------------------------------------------------------


def test_detach_a_project_the_employee_does_not_have_is_a_clean_success() -> None:
    employee = _make_employee()
    response = client.delete(f"/employees/{employee['id']}/projects/999999", headers=_admin_headers())
    assert response.status_code == 200
    assert response.json() == []
    _cleanup(employee_ids=[employee["id"]])


def test_detach_removes_the_project() -> None:
    employee = _make_employee()
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    client.post(f"/employees/{employee['id']}/projects", json={"name": project["name"]}, headers=_admin_headers())

    response = client.delete(f"/employees/{employee['id']}/projects/{project['id']}", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json() == []

    _cleanup(employee_ids=[employee["id"]], project_ids=[project["id"]])


def test_detach_from_an_inactive_employee_still_works() -> None:
    employee = _make_employee()
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    client.post(f"/employees/{employee['id']}/projects", json={"name": project["name"]}, headers=_admin_headers())
    client.delete(f"/employees/{employee['id']}", headers=_admin_headers())

    response = client.delete(f"/employees/{employee['id']}/projects/{project['id']}", headers=_admin_headers())

    assert response.status_code == 200

    _cleanup(employee_ids=[employee["id"]], project_ids=[project["id"]])


def test_detach_requires_authentication() -> None:
    assert client.delete("/employees/1/projects/1").status_code == 401


# ---------------------------------------------------------------------
# Authorization: self / manager-of-team / Admin, not CEO
# ---------------------------------------------------------------------


def test_self_attaches_own_project() -> None:
    employee = _make_employee()
    self_headers = _employee_headers(employee["email"])
    name = _unique_project_name()

    response = client.post(f"/employees/{employee['id']}/projects", json={"name": name}, headers=self_headers)

    assert response.status_code == 201
    _cleanup(employee_ids=[employee["id"]], project_ids=[response.json()[0]["id"]])


def test_self_can_mark_own_project_complete() -> None:
    """Confirmed decision: completion is self-reported and
    manager-correctable, not verified — the brief's "every user update
    their own info re: contact info, skills, projects" wins over a
    sign-off requirement.
    """
    employee = _make_employee()
    self_headers = _employee_headers(employee["email"])
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    client.post(f"/employees/{employee['id']}/projects", json={"name": project["name"]}, headers=self_headers)

    response = client.put(
        f"/employees/{employee['id']}/projects/{project['id']}",
        json={"completed_at": date.today().isoformat()},
        headers=self_headers,
    )

    assert response.status_code == 200
    assert next(p["completed_at"] for p in response.json() if p["id"] == project["id"]) is not None

    _cleanup(employee_ids=[employee["id"]], project_ids=[project["id"]])


def test_manager_attaches_project_for_own_team_member() -> None:
    fixture = _make_department_and_team()
    manager = fixture["manager"]
    member = _make_employee()
    client.put(f"/employees/{member['id']}", json={"team_id": fixture["team"]["id"]}, headers=_admin_headers())
    manager_headers = _employee_headers(manager["email"])
    name = _unique_project_name()

    response = client.post(f"/employees/{member['id']}/projects", json={"name": name}, headers=manager_headers)

    assert response.status_code == 201

    _cleanup(
        employee_ids=[manager["id"], member["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
        project_ids=[response.json()[0]["id"]],
    )


def test_manager_attempts_on_someone_not_on_their_team_returns_403() -> None:
    fixture = _make_department_and_team()
    manager_headers = _employee_headers(fixture["manager"]["email"])
    other_employee = _make_employee()

    response = client.post(
        f"/employees/{other_employee['id']}/projects", json={"name": _unique_project_name()}, headers=manager_headers
    )

    assert response.status_code == 403

    _cleanup(
        employee_ids=[fixture["manager"]["id"], other_employee["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_admin_attaches_for_any_employee() -> None:
    employee = _make_employee()
    name = _unique_project_name()
    response = client.post(f"/employees/{employee['id']}/projects", json={"name": name}, headers=_admin_headers())
    assert response.status_code == 201
    _cleanup(employee_ids=[employee["id"]], project_ids=[response.json()[0]["id"]])


def test_ceo_cannot_attach_project_for_someone_else() -> None:
    """Not CEO - consistent with the CEO having no general
    employee-editing power anywhere in this app.
    """
    employee = _make_employee()
    response = client.post(
        f"/employees/{employee['id']}/projects", json={"name": _unique_project_name()}, headers=_ceo_headers()
    )
    assert response.status_code == 403
    _cleanup(employee_ids=[employee["id"]])


# ---------------------------------------------------------------------
# The deferred project_id employee filter
# ---------------------------------------------------------------------


def test_list_employees_filters_by_project_id() -> None:
    has_project = _make_employee()
    lacks_project = _make_employee()
    name = _unique_project_name()
    attach = client.post(f"/employees/{has_project['id']}/projects", json={"name": name}, headers=_admin_headers())
    project_id = attach.json()[0]["id"]

    response = client.get(f"/employees?project_id={project_id}", headers=_admin_headers())

    assert response.status_code == 200
    ids = {e["id"] for e in response.json()}
    assert has_project["id"] in ids
    assert lacks_project["id"] not in ids

    _cleanup(employee_ids=[has_project["id"], lacks_project["id"]], project_ids=[project_id])


# ---------------------------------------------------------------------
# The get-or-create insert race
# ---------------------------------------------------------------------


def test_get_or_create_project_handles_the_insert_race(monkeypatch) -> None:
    """Same technique as skills' equivalent test: forces the initial
    SELECT to miss while the project genuinely already exists, so the
    INSERT hits a real UniqueViolation — the losing side of two
    containers racing to create the same project.
    """
    name = _unique_project_name()
    existing = project_repo.get_or_create_project(name)

    original_find = project_repo._find_project_by_lower_name
    calls = {"n": 0}

    def find_that_misses_once(conn, lower_name):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return original_find(conn, lower_name)

    monkeypatch.setattr(project_repo, "_find_project_by_lower_name", find_that_misses_once)

    result = project_repo.get_or_create_project(name)

    assert result.id == existing.id
    assert calls["n"] == 2

    _cleanup(project_ids=[existing.id])


# ---------------------------------------------------------------------
# GET /teams/{id}/achievements
# ---------------------------------------------------------------------


def test_achievements_returns_completed_projects_for_team_members() -> None:
    fixture = _make_department_and_team()
    manager = fixture["manager"]
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    finished = date.today()
    client.post(
        f"/employees/{manager['id']}/projects",
        json={"name": project["name"], "completed_at": finished.isoformat()},
        headers=_admin_headers(),
    )

    response = client.get(f"/teams/{fixture['team']['id']}/achievements", headers=_admin_headers())

    assert response.status_code == 200
    rows = response.json()
    assert any(
        r["employee_id"] == manager["id"] and r["project_id"] == project["id"] and r["completed_at"] == finished.isoformat()
        for r in rows
    )

    _cleanup(
        employee_ids=[manager["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
        project_ids=[project["id"]],
    )


def test_achievements_excludes_in_progress_assignments() -> None:
    fixture = _make_department_and_team()
    manager = fixture["manager"]
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    client.post(f"/employees/{manager['id']}/projects", json={"name": project["name"]}, headers=_admin_headers())

    response = client.get(f"/teams/{fixture['team']['id']}/achievements", headers=_admin_headers())

    assert response.status_code == 200
    assert not any(r["project_id"] == project["id"] for r in response.json())

    _cleanup(
        employee_ids=[manager["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
        project_ids=[project["id"]],
    )


def test_achievements_filters_by_month() -> None:
    fixture = _make_department_and_team()
    manager = fixture["manager"]
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=15)
    client.post(
        f"/employees/{manager['id']}/projects",
        json={"name": project["name"], "completed_at": last_month.isoformat()},
        headers=_admin_headers(),
    )
    this_month = f"{date.today():%Y-%m}"

    response = client.get(
        f"/teams/{fixture['team']['id']}/achievements?month={this_month}", headers=_admin_headers()
    )

    assert response.status_code == 200
    assert not any(r["project_id"] == project["id"] for r in response.json())

    _cleanup(
        employee_ids=[manager["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
        project_ids=[project["id"]],
    )


def test_achievements_omitted_month_returns_all_time() -> None:
    fixture = _make_department_and_team()
    manager = fixture["manager"]
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    long_ago = date(2020, 1, 15)
    client.post(
        f"/employees/{manager['id']}/projects",
        json={"name": project["name"], "completed_at": long_ago.isoformat()},
        headers=_admin_headers(),
    )

    response = client.get(f"/teams/{fixture['team']['id']}/achievements", headers=_admin_headers())

    assert response.status_code == 200
    assert any(r["project_id"] == project["id"] for r in response.json())

    _cleanup(
        employee_ids=[manager["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
        project_ids=[project["id"]],
    )


def test_achievements_malformed_month_returns_422() -> None:
    fixture = _make_department_and_team()
    response = client.get(
        f"/teams/{fixture['team']['id']}/achievements?month=2026-13", headers=_admin_headers()
    )
    assert response.status_code == 422
    _cleanup(
        employee_ids=[fixture["manager"]["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
    )


def test_achievements_unknown_team_returns_410() -> None:
    response = client.get("/teams/999999/achievements", headers=_admin_headers())
    assert response.status_code == 410


def test_achievements_requires_authentication() -> None:
    assert client.get("/teams/1/achievements").status_code == 401


def test_achievements_excludes_inactive_employees() -> None:
    fixture = _make_department_and_team()
    member = _make_employee()
    client.put(f"/employees/{member['id']}", json={"team_id": fixture["team"]["id"]}, headers=_admin_headers())
    project = client.post("/projects", json={"name": _unique_project_name()}, headers=_admin_headers()).json()
    client.post(
        f"/employees/{member['id']}/projects",
        json={"name": project["name"], "completed_at": date.today().isoformat()},
        headers=_admin_headers(),
    )
    client.delete(f"/employees/{member['id']}", headers=_admin_headers())

    response = client.get(f"/teams/{fixture['team']['id']}/achievements", headers=_admin_headers())

    assert response.status_code == 200
    assert not any(r["employee_id"] == member["id"] for r in response.json())

    _cleanup(
        employee_ids=[fixture["manager"]["id"], member["id"]],
        team_ids=[fixture["team"]["id"]],
        department_ids=[fixture["department"]["id"]],
        project_ids=[project["id"]],
    )
