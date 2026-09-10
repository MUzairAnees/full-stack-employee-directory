"""Tests for /employees: creation, self-vs-Admin edit rights, the
org-chart derivation, and the delete guards (CEO, last active Admin,
active direct reports).
"""

import uuid

from fastapi.testclient import TestClient

import app.repositories.db as db
from app.main import app

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


def _deactivate(employee_id: int, headers: dict) -> None:
    """Cleanup helper: soft-deletes via the real DELETE endpoint, so
    cleanup exercises the same path a real deactivation would.
    """
    client.delete(f"/employees/{employee_id}", headers=headers)


# ---------------------------------------------------------------------
# Create: authorization
# ---------------------------------------------------------------------


def test_admin_can_create_an_employee() -> None:
    headers = _admin_headers()
    response = client.post("/employees", json=_valid_create_body(), headers=headers)
    assert response.status_code == 201
    assert response.json()["is_active"] is True

    _deactivate(response.json()["id"], headers)


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
# Create: validation and uniqueness
# ---------------------------------------------------------------------


def test_create_with_bad_work_location_id_returns_422_naming_the_field() -> None:
    """The FK violation is translated to 422 and names which field was
    wrong - employees have four FK columns, so "invalid reference" alone
    wouldn't say which one.
    """
    headers = _admin_headers()
    response = client.post("/employees", json=_valid_create_body(work_location_id=999999), headers=headers)
    assert response.status_code == 422
    assert response.json()["field"] == "work_location_id"


def test_create_duplicate_email_returns_409() -> None:
    headers = _admin_headers()
    body = _valid_create_body()
    first = client.post("/employees", json=body, headers=headers)
    assert first.status_code == 201

    duplicate = client.post("/employees", json=body, headers=headers)
    assert duplicate.status_code == 409

    _deactivate(first.json()["id"], headers)


def test_create_duplicate_email_case_variant_returns_409() -> None:
    """The LOWER(email) unique index stops two rows differing only by
    case - proving that, not just the exact-match duplicate above.
    """
    headers = _admin_headers()
    body = _valid_create_body()
    first = client.post("/employees", json=body, headers=headers)
    assert first.status_code == 201

    case_variant = {**body, "email": body["email"].upper()}
    duplicate = client.post("/employees", json=case_variant, headers=headers)
    assert duplicate.status_code == 409

    _deactivate(first.json()["id"], headers)


# ---------------------------------------------------------------------
# The org-chart derivation
# ---------------------------------------------------------------------


def test_manager_id_is_derived_to_the_ceo_when_created_with_no_team() -> None:
    """The org-chart derivation (_compute_manager_id): anyone created
    with no team gets manager_id = the CEO's id. team assignment isn't a
    capability that exists yet (slice 5), so this covers every employee
    created this slice.
    """
    headers = _admin_headers()
    ceo_id = _ceo_id()

    created = client.post("/employees", json=_valid_create_body(), headers=headers).json()

    assert created["team_id"] is None
    assert created["manager_id"] == ceo_id

    _deactivate(created["id"], headers)


def test_manager_id_submitted_in_the_request_body_is_not_honored() -> None:
    """manager_id isn't on EmployeeCreate at all (see
    app/schemas/employee.py) - a caller who submits it anyway gets the
    derived value back, not whatever they sent. Pydantic silently
    ignores the unknown field; this proves the RESPONSE reflects the
    derivation, not attacker-controlled input.
    """
    headers = _admin_headers()
    ceo_id = _ceo_id()

    body = _valid_create_body()
    body["manager_id"] = 999999

    created = client.post("/employees", json=body, headers=headers).json()

    assert created["manager_id"] == ceo_id
    assert created["manager_id"] != 999999

    _deactivate(created["id"], headers)


# ---------------------------------------------------------------------
# Update: self vs. Admin
# ---------------------------------------------------------------------


def test_put_self_can_update_first_name_last_name_and_phone() -> None:
    admin_headers = _admin_headers()
    created = client.post("/employees", json=_valid_create_body(), headers=admin_headers).json()

    self_headers = {"Authorization": f"Bearer {_token_for(created['email'], _TEST_PASSWORD)}"}
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

    _deactivate(created["id"], admin_headers)


def test_put_someone_else_returns_403() -> None:
    admin_headers = _admin_headers()
    employee_a = client.post("/employees", json=_valid_create_body(), headers=admin_headers).json()
    employee_b = client.post("/employees", json=_valid_create_body(), headers=admin_headers).json()

    a_headers = {"Authorization": f"Bearer {_token_for(employee_a['email'], _TEST_PASSWORD)}"}
    response = client.put(f"/employees/{employee_b['id']}", json={"first_name": "Hacked"}, headers=a_headers)

    assert response.status_code == 403

    _deactivate(employee_a["id"], admin_headers)
    _deactivate(employee_b["id"], admin_headers)


def test_put_self_phone_whitespace_only_stores_as_null_not_empty_string() -> None:
    """phone strips, and empty-after-strip becomes NULL, not "" - the
    same invisible-value bug fixed for first_name/last_name (see
    app/schemas/common.py's OptionalTrimmedText), but here in a column
    that can properly express "not set" (unlike first_name/last_name,
    which are NOT NULL, so min_length=1 is their fix instead).
    """
    admin_headers = _admin_headers()
    created = client.post("/employees", json=_valid_create_body(phone="555-1234"), headers=admin_headers).json()
    assert created["phone"] == "555-1234"

    self_headers = {"Authorization": f"Bearer {_token_for(created['email'], _TEST_PASSWORD)}"}
    response = client.put(f"/employees/{created['id']}", json={"phone": "   "}, headers=self_headers)

    assert response.status_code == 200
    assert response.json()["phone"] is None

    _deactivate(created["id"], admin_headers)


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
    headers = _admin_headers()

    response = client.delete(f"/employees/{ceo_id}", headers=headers)
    assert response.status_code == 409

    still_active = client.get(f"/employees/{ceo_id}", headers=headers)
    assert still_active.json()["is_active"] is True


def test_delete_the_last_active_admin_is_blocked() -> None:
    """At least one active Admin must remain (see soft_delete_employee) -
    without it nobody could create employees, reactivate anyone, or fix
    anything through the API, and the CEO has no employee powers to do
    it either. Since DELETE requires the ADMIN role (require_role), the
    only caller who could ever be eligible once the active-Admin count
    is down to one IS that one Admin - so the reachable case is always
    "the last Admin deletes themselves," never a second party, and this
    test exercises exactly that.

    Reaching "exactly one active Admin" needs the seeded Admin
    temporarily deactivated - there's no way to do that through the API
    without tripping this very guard, so it's a direct SQL write, same
    technique test_auth.py uses for its deactivated-account setup.
    Restored in a finally block regardless of outcome.
    """
    admin_headers = _admin_headers()
    lone_admin = client.post("/employees", json=_valid_create_body(role="ADMIN"), headers=admin_headers).json()

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE employees SET is_active = false WHERE email = %s", (_ADMIN_EMAIL,))

        lone_admin_headers = {"Authorization": f"Bearer {_token_for(lone_admin['email'], _TEST_PASSWORD)}"}
        response = client.delete(f"/employees/{lone_admin['id']}", headers=lone_admin_headers)
        assert response.status_code == 409
    finally:
        with conn.cursor() as cur:
            cur.execute("UPDATE employees SET is_active = true WHERE email = %s", (_ADMIN_EMAIL,))
            cur.execute("UPDATE employees SET is_active = false WHERE id = %s", (lone_admin["id"],))


def test_delete_blocked_by_active_direct_reports() -> None:
    """A manager can't be deactivated while someone's manager_id still
    points at them - that would leave a report pointing at an inactive
    person, a broken org chart, visible in the demo (see
    soft_delete_employee).

    No team-assignment flow exists yet (slice 5) to reach this org-chart
    shape through the API - every employee created this slice gets
    manager_id = the CEO (see _compute_manager_id) - so a direct SQL
    write sets up the one precondition (a report whose manager_id points
    at a non-CEO employee), and the real DELETE endpoint is what's
    actually under test.
    """
    headers = _admin_headers()
    manager = client.post("/employees", json=_valid_create_body(role="MANAGER"), headers=headers).json()
    report = client.post("/employees", json=_valid_create_body(), headers=headers).json()

    conn = db.get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE employees SET manager_id = %s WHERE id = %s", (manager["id"], report["id"]))

    response = client.delete(f"/employees/{manager['id']}", headers=headers)
    assert response.status_code == 409

    still_active = client.get(f"/employees/{manager['id']}", headers=headers)
    assert still_active.json()["is_active"] is True

    with conn.cursor() as cur:
        cur.execute("UPDATE employees SET manager_id = %s WHERE id = %s", (_ceo_id(), report["id"]))
    _deactivate(report["id"], headers)
    _deactivate(manager["id"], headers)


# ---------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------


def test_list_filters_by_q() -> None:
    headers = _admin_headers()
    unique_first_name = f"Findable{uuid.uuid4().hex[:8]}"
    created = client.post("/employees", json=_valid_create_body(first_name=unique_first_name), headers=headers).json()

    response = client.get(f"/employees?q={unique_first_name}", headers=headers)
    assert response.status_code == 200
    assert any(e["id"] == created["id"] for e in response.json())

    _deactivate(created["id"], headers)


def test_list_filters_by_expertise_id() -> None:
    headers = _admin_headers()
    frontend_id = next(v["id"] for v in client.get("/expertise", headers=headers).json() if v["name"] == "Frontend")
    created = client.post("/employees", json=_valid_create_body(expertise_id=frontend_id), headers=headers).json()

    response = client.get(f"/employees?expertise_id={frontend_id}", headers=headers)
    assert response.status_code == 200
    assert any(e["id"] == created["id"] for e in response.json())

    _deactivate(created["id"], headers)


def test_list_filters_by_available() -> None:
    headers = _admin_headers()
    created = client.post("/employees", json=_valid_create_body(project_availability=False), headers=headers).json()

    unavailable = client.get("/employees?available=false", headers=headers)
    assert unavailable.status_code == 200
    assert any(e["id"] == created["id"] for e in unavailable.json())

    available_only = client.get("/employees?available=true", headers=headers)
    assert not any(e["id"] == created["id"] for e in available_only.json())

    _deactivate(created["id"], headers)
