"""Tests for /expertise."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_CEO_EMAIL = "ceo@example.com"
_CEO_PASSWORD = "Password123!"


def _ceo_headers() -> dict:
    token = client.post("/login", json={"email": _CEO_EMAIL, "password": _CEO_PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_expertise_requires_authentication() -> None:
    """Same gap, same fix as /work-locations: slice 1 code, never given
    the auth dependency the other GETs use. Not explicitly named in the
    slice 4 ask, but the stated reasoning applies here word for word.
    """
    assert client.get("/expertise").status_code == 401


def test_list_expertise_returns_seeded_values() -> None:
    """All four seeded expertise values come back."""
    response = client.get("/expertise", headers=_ceo_headers())
    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert names == {"Backend", "Frontend", "DevOps", "Support"}
