"""Authentication: password verification and JWT issuance/validation."""

import os
import time

import bcrypt
import jwt

from app.models.employee import Employee
from app.repositories import employee_repository as repo

# Workshop-scope shortcut: a hardcoded fallback secret. Never commit a
# real one. Production would pull this from Secrets Manager; that's an
# infra/ change, out of scope here (see README).
_JWT_SECRET = os.environ.get("JWT_SECRET", "dev-placeholder-not-a-real-secret")
_JWT_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 8 * 60 * 60  # 8h; no refresh flow this slice (known gap)

# Same cost factor seed.sql's bootstrap hashes were generated with. Both
# a real check and the dummy check below always cost the same because
# they share this one constant, not by coincidence.
_BCRYPT_ROUNDS = 12

# Precomputed once at import, not per-request: an unknown email must
# still pay for exactly one bcrypt.checkpw() against a hash of the same
# cost factor as a real one, or the timing difference alone reveals which
# emails are registered.
_DUMMY_HASH = bcrypt.hashpw(
    b"dummy-password-for-constant-time-auth", bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
)


class AuthenticationError(Exception):
    """Raised for any login failure. Deliberately one exception type for
    unknown email, wrong password, and a deactivated account — the
    caller must not be able to tell them apart from the exception alone.
    """


def authenticate(email: str, password: str) -> str:
    """Verifies credentials and returns a signed JWT.

    Args:
        email: The submitted email.
        password: The submitted plaintext password.

    Returns:
        str: A signed JWT for the authenticated employee.

    Raises:
        AuthenticationError: unknown email, wrong password, or a
            deactivated account — identical in every observable way,
            including timing (see _DUMMY_HASH above).
    """
    employee = repo.get_employee_by_email(email)

    hash_to_check = employee.password_hash.encode() if employee else _DUMMY_HASH
    password_matches = bcrypt.checkpw(password.encode(), hash_to_check)

    if employee is None or not password_matches or not employee.is_active:
        raise AuthenticationError("invalid email or password")

    return _issue_token(employee)


def _issue_token(employee: Employee) -> str:
    """Signs a short-lived JWT identifying this employee."""
    now = int(time.time())
    payload = {"sub": str(employee.id), "iat": now, "exp": now + _TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> int:
    """Decodes a JWT and returns the employee id it was issued for.

    Args:
        token: The raw JWT (no "Bearer " prefix).

    Returns:
        int: The employee id from the token's "sub" claim.

    Raises:
        jwt.PyJWTError: for any invalid, tampered, or expired token.
    """
    payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    return int(payload["sub"])
