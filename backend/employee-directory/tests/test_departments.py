"""Tests for /departments."""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.repositories.db as db
from app.main import app
from conftest import hard_delete_departments

client = TestClient(app)

_CEO_EMAIL = "ceo@example.com"
_CEO_PASSWORD = "ceo1234"
_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASSWORD = "admin1234"


def _token_for(email: str, password: str) -> str:
    response = client.post("/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def _ceo_headers() -> dict:
    return {"Authorization": f"Bearer {_token_for(_CEO_EMAIL, _CEO_PASSWORD)}"}


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_token_for(_ADMIN_EMAIL, _ADMIN_PASSWORD)}"}


def _unique_name() -> str:
    return f"Test Dept {uuid.uuid4().hex[:8]}"


def _cleanup(*department_ids: int) -> None:
    """Hard-deletes departments — test teardown only, the real DELETE
    always soft-deletes. Soft-deleting via the API (as these tests still
    do to exercise the endpoint itself) leaves the row in the table
    forever; this removes it for real once the test is done with it.
    """
    hard_delete_departments(db.get_connection(), list(department_ids))


def test_ceo_can_create_list_get_rename_and_soft_delete_a_department() -> None:
    headers = _ceo_headers()
    name = _unique_name()

    created = client.post("/departments", json={"name": name}, headers=headers)
    assert created.status_code == 201
    department_id = created.json()["id"]
    assert created.json()["is_active"] is True

    listed = client.get("/departments", headers=headers)
    assert listed.status_code == 200
    assert any(d["id"] == department_id for d in listed.json())

    fetched = client.get(f"/departments/{department_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["name"] == name

    renamed_name = _unique_name()
    renamed = client.put(f"/departments/{department_id}", json={"name": renamed_name}, headers=headers)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == renamed_name

    deleted = client.delete(f"/departments/{department_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False

    # Soft delete: the row survives, just inactive - still fetchable by id.
    still_fetchable = client.get(f"/departments/{department_id}", headers=headers)
    assert still_fetchable.status_code == 200
    assert still_fetchable.json()["is_active"] is False

    # ...but hidden from the default list.
    listed_again = client.get("/departments", headers=headers)
    assert not any(d["id"] == department_id for d in listed_again.json())

    # ...unless include_inactive is set.
    listed_with_inactive = client.get("/departments?include_inactive=true", headers=headers)
    assert any(d["id"] == department_id for d in listed_with_inactive.json())

    _cleanup(department_id)


def test_get_unknown_department_returns_410() -> None:
    response = client.get("/departments/999999", headers=_ceo_headers())
    assert response.status_code == 410


def test_delete_is_idempotent_returns_200_not_409() -> None:
    headers = _ceo_headers()
    department_id = client.post("/departments", json={"name": _unique_name()}, headers=headers).json()["id"]

    first = client.delete(f"/departments/{department_id}", headers=headers)
    assert first.status_code == 200

    second = client.delete(f"/departments/{department_id}", headers=headers)
    assert second.status_code == 200
    assert second.json()["is_active"] is False

    _cleanup(department_id)


def test_create_with_name_of_soft_deleted_department_returns_409() -> None:
    headers = _ceo_headers()
    name = _unique_name()
    department_id = client.post("/departments", json={"name": name}, headers=headers).json()["id"]
    client.delete(f"/departments/{department_id}", headers=headers)

    duplicate = client.post("/departments", json={"name": name}, headers=headers)
    assert duplicate.status_code == 409

    _cleanup(department_id)


def test_rename_to_an_existing_name_returns_409() -> None:
    headers = _ceo_headers()
    name_a = _unique_name()
    name_b = _unique_name()
    id_a = client.post("/departments", json={"name": name_a}, headers=headers).json()["id"]
    id_b = client.post("/departments", json={"name": name_b}, headers=headers).json()["id"]

    response = client.put(f"/departments/{id_a}", json={"name": name_b}, headers=headers)
    assert response.status_code == 409

    _cleanup(id_a, id_b)


def test_put_can_restore_a_soft_deleted_department() -> None:
    headers = _ceo_headers()
    department_id = client.post("/departments", json={"name": _unique_name()}, headers=headers).json()["id"]
    client.delete(f"/departments/{department_id}", headers=headers)

    restored = client.put(f"/departments/{department_id}", json={"is_active": True}, headers=headers)
    assert restored.status_code == 200
    assert restored.json()["is_active"] is True

    _cleanup(department_id)


def test_put_cannot_set_is_active_false() -> None:
    """This rule (PUT can only ever restore, never deactivate) is new
    this slice — pinned so it fails loudly if is_active is ever loosened
    back to a plain bool instead of Literal[True] | None.
    """
    headers = _ceo_headers()
    department_id = client.post("/departments", json={"name": _unique_name()}, headers=headers).json()["id"]

    response = client.put(f"/departments/{department_id}", json={"is_active": False}, headers=headers)
    assert response.status_code == 422

    _cleanup(department_id)


def test_create_rejects_empty_name() -> None:
    response = client.post("/departments", json={"name": ""}, headers=_ceo_headers())
    assert response.status_code == 422


def test_create_rejects_whitespace_only_name() -> None:
    response = client.post("/departments", json={"name": "   "}, headers=_ceo_headers())
    assert response.status_code == 422


def test_create_rejects_name_over_max_length() -> None:
    response = client.post("/departments", json={"name": "x" * 256}, headers=_ceo_headers())
    assert response.status_code == 422


def test_create_strips_name_so_padded_duplicate_is_rejected() -> None:
    """The strip matters more than the reject (see app/schemas/common.py):
    without it, "Sales" and " Sales " are distinct strings as far as the
    UNIQUE constraint is concerned, and you'd get two departments in the
    list nobody could tell apart.
    """
    headers = _ceo_headers()
    name = _unique_name()
    department_id = client.post("/departments", json={"name": name}, headers=headers).json()["id"]

    padded_duplicate = client.post("/departments", json={"name": f" {name} "}, headers=headers)
    assert padded_duplicate.status_code == 409

    _cleanup(department_id)


@pytest.mark.parametrize(
    "make_request",
    [
        lambda headers: client.post("/departments", json={"name": "irrelevant"}, headers=headers),
        lambda headers: client.put("/departments/999999", json={"name": "irrelevant"}, headers=headers),
        lambda headers: client.delete("/departments/999999", headers=headers),
    ],
    ids=["POST", "PUT", "DELETE"],
)
def test_department_write_requires_ceo_role(make_request) -> None:
    """Authenticated as the seeded Admin — wrong role, not no role.
    department 999999 doesn't need to exist: require_role rejects before
    the route body (and any DB lookup) ever runs.
    """
    response = make_request(_admin_headers())
    assert response.status_code == 403


@pytest.mark.parametrize(
    "make_request",
    [
        lambda: client.post("/departments", json={"name": "irrelevant"}),
        lambda: client.put("/departments/999999", json={"name": "irrelevant"}),
        lambda: client.delete("/departments/999999"),
    ],
    ids=["POST", "PUT", "DELETE"],
)
def test_department_write_requires_authentication(make_request) -> None:
    """No Authorization header at all — require_role wraps current_user,
    so this must be 401, not 403: authentication is checked first.
    """
    response = make_request()
    assert response.status_code == 401


def test_list_and_get_require_authentication() -> None:
    assert client.get("/departments").status_code == 401
    assert client.get("/departments/1").status_code == 401


# test_delete_blocked_by_active_employees: this used to be a
# @pytest.mark.skip stub, waiting on teams (slice 3's note: "there's no
# way yet to attach an active employee to a department"). Teams exist
# now — the real, un-skipped version of this test lives in
# tests/test_teams.py as
# test_department_delete_blocked_by_an_active_team_with_an_active_employee,
# alongside the team fixtures it actually needs, rather than duplicated
# here.
