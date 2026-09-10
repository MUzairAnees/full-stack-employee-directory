"""Tests for authentication: login and current_user (/me).

Proving failed login gives nothing away, a deactivated account can't log
in (or keep using a token it got before being deactivated), current_user
rejects every broken-token shape, and email is treated as case-insensitive:
  1. login succeeds with correct credentials
  2. wrong password -> 401
  3. unknown email -> 401, IDENTICAL body to #2
  4. deactivated employee -> 401 even with the right password
  5. missing/malformed Authorization header -> 401
  6. tampered token -> 401
  7. expired token -> 401
  8. a valid token stops working the moment the account is deactivated,
     not just once the token expires
  9. login is case-insensitive on email
"""

import bcrypt
import jwt
from fastapi.testclient import TestClient

import app.repositories.db as db
from app.main import app
from app.services.auth_service import _BCRYPT_ROUNDS, _JWT_ALGORITHM, _JWT_SECRET

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


def test_me_tampered_token_returns_401() -> None:
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

    response = client.get("/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert response.status_code == 401


def test_me_expired_token_returns_401() -> None:
    """A different failure path from tampering - a token that's
    correctly signed but simply too old. Minted directly rather than
    waiting 8h for a real one to expire.
    """
    expired_token = jwt.encode({"sub": "1", "iat": 0, "exp": 1}, _JWT_SECRET, algorithm=_JWT_ALGORITHM)
    response = client.get("/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401


def test_deactivating_employee_immediately_invalidates_their_existing_token() -> None:
    """current_user re-reads the employee from the database on every
    call rather than trusting the JWT payload - proving that holds even
    for a token that WAS valid at issue time. If this ever regresses to
    trusting the token alone, a deactivated employee keeps full access
    until their token naturally expires (up to 8h) instead of losing it
    on their very next request.

    No employee-update endpoint exists yet (that's a later slice), so
    deactivation here is a direct database write, same technique this
    file used before the deactivated demo account was seeded instead.
    """
    email = "temp-deactivation-test@example.com"
    password = "test-password-123"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()

    conn = db.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO employees (first_name, last_name, email, password_hash, role,
                work_location_id, expertise_id, is_active)
            VALUES ('Temp', 'ActiveThenNot', %s, %s, 'EMPLOYEE',
                (SELECT id FROM work_locations WHERE name = 'Remote'),
                (SELECT id FROM expertise WHERE name = 'Backend'), true)
            ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, is_active = true
            """,
            (email, password_hash),
        )

    token = client.post("/login", json={"email": email, "password": password}).json()["access_token"]

    still_active = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert still_active.status_code == 200

    with conn.cursor() as cur:
        cur.execute("UPDATE employees SET is_active = false WHERE email = %s", (email,))

    # The SAME, still-unexpired token must now be rejected.
    after_deactivation = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert after_deactivation.status_code == 401


def test_login_is_case_insensitive_on_email() -> None:
    """email is UNIQUE and IS the login - without normalizing case,
    "CEO@example.com" and "ceo@example.com" would be able to register as
    two different accounts once slice 4 allows creating employees, or
    (before that's even possible) simply fail to log in an existing user
    who typed their email in a different case than it was stored in.
    """
    response = client.post("/login", json={"email": _CEO_EMAIL.upper(), "password": _CEO_PASSWORD})
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_finds_a_mixed_case_stored_email() -> None:
    """The test above only varies the INPUT case against an
    already-lowercase seeded row - that passes even with a plain
    `WHERE email = %s` lookup, since auth_service lowercases input
    before querying and every seeded email happens to already be
    lowercase. It never actually distinguishes `email = %s` from
    `LOWER(email) = %s`.

    This one does: it stores a row with mixed case directly (no
    employee-create endpoint exists yet to normalize on write, so this
    simulates one that slipped through) and proves login still finds it.
    Under a plain `email = %s` lookup this row would be UNREACHABLE -
    permanently unable to log in, no error explaining why.
    """
    email_mixed_case = "MixedCase.User@Example.com"
    password = "test-password-123"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()

    conn = db.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO employees (first_name, last_name, email, password_hash, role,
                work_location_id, expertise_id, is_active)
            VALUES ('Mixed', 'Case', %s, %s, 'EMPLOYEE',
                (SELECT id FROM work_locations WHERE name = 'Remote'),
                (SELECT id FROM expertise WHERE name = 'Backend'), true)
            ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, is_active = true
            """,
            (email_mixed_case, password_hash),
        )

    response = client.post("/login", json={"email": email_mixed_case.lower(), "password": password})
    assert response.status_code == 200
    assert "access_token" in response.json()
