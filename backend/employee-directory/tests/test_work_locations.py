"""Tests for /work-locations: happy paths, not-found, and edge cases."""

import json

from fastapi.testclient import TestClient

from app.main import app
from conftest import make_function_url_event
from function import handler

client = TestClient(app)

_CEO_EMAIL = "ceo@example.com"
_CEO_PASSWORD = "ceo1234"


def _ceo_headers() -> dict:
    token = client.post("/login", json={"email": _CEO_EMAIL, "password": _CEO_PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_work_locations_requires_authentication() -> None:
    """Slice 4 guard: this endpoint had no auth dependency at all since
    slice 1 — a stranger with the CloudFront URL could curl it with no
    token. Fixed; this pins it so it can't silently regress.
    """
    assert client.get("/work-locations").status_code == 401


def test_list_work_locations_includes_seeded_remote() -> None:
    """The seeded 'Remote' location comes back through the full stack:
    migration -> repository -> service -> schema -> controller.
    """
    response = client.get("/work-locations", headers=_ceo_headers())
    assert response.status_code == 200
    names = [location["name"] for location in response.json()]
    assert "Remote" in names


def test_work_locations_path_prefix_both_shapes_resolve_the_same() -> None:
    """The AWS-vs-local path divergence, proven on a real business
    endpoint, not just /health: CloudFront forwards the full,
    "/api/employee-directory"-prefixed path unstripped, while the local
    proxy strips it before the Lambda ever sees the request. Both must
    resolve to the same 200 with the same body. Needs a real token now
    that this endpoint requires authentication.
    """
    headers = {"Authorization": _ceo_headers()["Authorization"]}
    prefixed_event = make_function_url_event("/api/employee-directory/work-locations")
    prefixed_event["headers"]["authorization"] = headers["Authorization"]
    unprefixed_event = make_function_url_event("/work-locations")
    unprefixed_event["headers"]["authorization"] = headers["Authorization"]

    prefixed = handler(prefixed_event, None)
    unprefixed = handler(unprefixed_event, None)

    assert prefixed["statusCode"] == 200
    assert unprefixed["statusCode"] == 200
    assert json.loads(prefixed["body"]) == json.loads(unprefixed["body"])


def test_get_work_location_returns_200_for_a_real_id() -> None:
    """A real, existing id round-trips correctly through get-by-id."""
    headers = _ceo_headers()
    listed = client.get("/work-locations", headers=headers).json()
    remote_id = next(loc["id"] for loc in listed if loc["name"] == "Remote")

    response = client.get(f"/work-locations/{remote_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["name"] == "Remote"


def test_get_work_location_410_for_unknown_id() -> None:
    """An id that can't exist yields 410 Gone, not 404.

    410, not 404: per workshop guidance, this platform's CloudFront
    reserves 404 for its SPA deep-link fallback (infra/cloudfront.tf
    rewrites every 404 to 200 /index.html, distribution-wide). Domain
    not-found uses 410 instead, mapped in exactly one place — the
    app-level exception handler in app/main.py. Unlike the old 404
    version of this test, 410 is NOT touched by that CloudFront rewrite,
    so this status code is expected to survive unchanged all the way
    through to a real client — confirmed manually against the deployed
    CloudFront URL, not just here against the app directly.
    """
    response = client.get("/work-locations/999999", headers=_ceo_headers())
    assert response.status_code == 410
    assert "detail" in response.json()


def test_get_work_location_non_integer_id_returns_422_not_500() -> None:
    """FastAPI's path-parameter type validation rejects a non-integer id
    before it ever reaches our code — proving that, not just assuming it.
    """
    response = client.get("/work-locations/abc", headers=_ceo_headers())
    assert response.status_code == 422


def test_remote_serialises_with_null_address_fields_present() -> None:
    """address_line_1/city/state/zip are nullable and Remote has none set.
    They must appear as explicit JSON null, not be silently omitted from
    the response — an omitted key looks like a schema bug to any client
    that checks `"city" in data` rather than `data["city"] is None`.
    """
    headers = _ceo_headers()
    listed = client.get("/work-locations", headers=headers).json()
    remote = next(loc for loc in listed if loc["name"] == "Remote")

    for field in ("address_line_1", "city", "state", "zip"):
        assert field in remote
        assert remote[field] is None


def test_list_work_locations_returns_empty_list_not_410_when_nothing_matches(monkeypatch) -> None:
    """A list endpoint with zero results is an empty collection, not an
    error. Guards against the common bug of treating "no rows" the same
    as "no such row" — /work-locations/{id} correctly 410s on the latter,
    but the list endpoint must never do that just because it found none.
    """
    import app.services.work_location_service as service_module

    monkeypatch.setattr(service_module, "list_work_locations", lambda: [])

    response = client.get("/work-locations", headers=_ceo_headers())

    assert response.status_code == 200
    assert response.json() == []
