"""Tests for GET /health.

Two angles on purpose:
  - test_health_returns_ok exercises the FastAPI route directly.
  - test_health_via_lambda_function_url_event exercises the real Lambda
    entry point with the exact event shape AWS sends, where CloudFront has
    NOT stripped the "/api/employee-directory" prefix. This is the case
    that would 404 in production if api_gateway_base_path were missing or
    wrong, and it's cheap to catch here instead of after a deploy.
"""

from fastapi.testclient import TestClient

from app.main import app
from conftest import make_function_url_event
from function import handler


def test_health_returns_ok() -> None:
    """The route responds correctly when called directly, no Lambda involved."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_via_lambda_function_url_event() -> None:
    """The route still resolves when invoked through Mangum with a raw,
    unstripped AWS path — the exact shape CloudFront forwards on AWS.
    """
    event = make_function_url_event("/api/employee-directory/health")

    response = handler(event, None)

    assert response["statusCode"] == 200
