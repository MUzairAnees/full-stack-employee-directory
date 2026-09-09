"""Tests for /expertise."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_list_expertise_returns_seeded_values() -> None:
    """All four seeded expertise values come back."""
    response = client.get("/expertise")
    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert names == {"Backend", "Frontend", "DevOps", "Support"}
