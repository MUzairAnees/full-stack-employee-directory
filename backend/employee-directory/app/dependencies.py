"""Shared FastAPI dependencies."""

from collections.abc import Callable

import jwt
from fastapi import Depends, Header, HTTPException

from app.models.employee import Employee
from app.models.role import Role
from app.repositories import employee_repository as repo
from app.services.auth_service import decode_token


def current_user(authorization: str | None = Header(default=None)) -> Employee:
    """Resolves the authenticated employee from the Authorization header.

    Re-reads the employee from the database on every call rather than
    trusting the JWT payload, so a deactivated account is rejected on
    the next request rather than only once the token expires.

    Args:
        authorization: The raw "Authorization" header, e.g. "Bearer <jwt>".

    Returns:
        Employee: The authenticated, active employee.

    Raises:
        HTTPException: 401 if the header is missing/malformed, the token
            is invalid/tampered/expired, or the employee no longer exists
            or is inactive. The detail is deliberately generic — which of
            these it was is not exposed.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="not authenticated")

    token = authorization.removeprefix("Bearer ")

    try:
        employee_id = decode_token(token)
    except jwt.PyJWTError as err:
        raise HTTPException(status_code=401, detail="not authenticated") from err

    employee = repo.get_employee_by_id(employee_id)
    if employee is None or not employee.is_active:
        raise HTTPException(status_code=401, detail="not authenticated")

    return employee


def require_role(*roles: Role) -> Callable[[Employee], Employee]:
    """Builds a dependency requiring the current user to have one of the
    given roles. Wraps current_user rather than duplicating it, so
    FastAPI resolves that first: no/bad token -> 401 before role is ever
    checked; a valid token with the wrong role -> 403.

    Args:
        *roles: The roles allowed to proceed.

    Returns:
        A dependency callable for use with Depends(require_role(...)).
    """

    def dependency(employee: Employee = Depends(current_user)) -> Employee:
        if employee.role not in roles:
            raise HTTPException(status_code=403, detail="you don't have permission")
        return employee

    return dependency
