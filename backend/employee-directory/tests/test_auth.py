"""Tests for authentication: login and current_user (/me).

Six tests, matching what this slice is actually for — proving failed
login gives nothing away, a deactivated account can't log in, and
current_user rejects every broken-token shape:
  1. login succeeds with correct credentials
  2. wrong password -> 401
  3. unknown email -> 401, IDENTICAL body to #2
  4. deactivated employee -> 401 even with the right password
  5. missing/malformed Authorization header -> 401
  6. tampered/expired token -> 401
"""

import jwt
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_service import _JWT_ALGORITHM, _JWT_SECRET

client = TestClient(app)

_CEO_EMAIL = "ceo@example.com"
_CEO_PASSWORD = "Password123!"
# Same permanently-seeded account seed.sql defines, so this test needs no
# database writes of its own and this password works against AWS too.
_DEACTIVATED_EMAIL = "deactivated@example.com"
_DEACTIVATED_PASSWORD = "Password123!"


def test_login_succeeds_with_correct_credentials() -> None:
    response = client.post("/login", json={"email": _CEO_EMAIL, "password": _CEO_PASSWORD})
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_wrong_password_returns_401() -> None:
    response = client.post("/login", json={"email": _CEO_EMAIL, "password": "wrong-password"})
    assert response.status_code == 401


def test_login_unknown_email_returns_401_identical_to_wrong_password() -> None:
    """The response must be indistinguishable from a wrong-password
    failure — otherwise the difference alone reveals which emails exist.
    """
    wrong_password = client.post("/login", json={"email": _CEO_EMAIL, "password": "wrong-password"})
    unknown_email = client.post("/login", json={"email": "nobody@example.com", "password": "wrong-password"})

    assert unknown_email.status_code == wrong_password.status_code == 401
    assert unknown_email.json() == wrong_password.json()


def test_login_deactivated_employee_returns_401_even_with_correct_password() -> None:
    """A deactivated account must be rejected even with the right
    password. Uses the permanently-seeded deactivated demo account
    (seed.sql) rather than inserting one — that account also needs to
    exist against AWS for smoke_test.py, so it's seeded once, not
    created ad hoc by this test.
    """
    response = client.post("/login", json={"email": _DEACTIVATED_EMAIL, "password": _DEACTIVATED_PASSWORD})
    assert response.status_code == 401


def test_me_missing_or_malformed_authorization_header_returns_401() -> None:
    no_header = client.get("/me")
    malformed = client.get("/me", headers={"Authorization": "not-a-bearer-token"})

    assert no_header.status_code == 401
    assert malformed.status_code == 401


def test_me_tampered_or_expired_token_returns_401() -> None:
    login_response = client.post("/login", json={"email": _CEO_EMAIL, "password": _CEO_PASSWORD})
    real_token = login_response.json()["access_token"]
    # Reverse the signature segment rather than flipping its last
    # character: base64url's last character can encode only a few
    # meaningful bits (padding bits fill the rest), so a naive
    # single-character substitution there can decode to the exact same
    # signature bytes and produce a token that verifies as valid — caught
    # by this test itself the first time it ran. Reversing guarantees
    # different bytes.
    header, payload, signature = real_token.split(".")
    tampered_token = f"{header}.{payload}.{signature[::-1]}"

    tampered = client.get("/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert tampered.status_code == 401

    expired_token = jwt.encode({"sub": "1", "iat": 0, "exp": 1}, _JWT_SECRET, algorithm=_JWT_ALGORITHM)
    expired = client.get("/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert expired.status_code == 401
