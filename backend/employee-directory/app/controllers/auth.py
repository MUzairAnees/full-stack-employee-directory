"""Routes for authentication."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import current_user
from app.models.employee import Employee
from app.schemas.auth import CurrentUserOut, LoginRequest, TokenResponse
from app.services.auth_service import AuthenticationError, authenticate

router = APIRouter(tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"description": "Invalid email or password — unknown email, wrong password, and a deactivated "
              "account are all indistinguishable on purpose, same body and status for all three."},
        422: {"description": "Request body missing email or password."},
    },
)
def login(body: LoginRequest) -> TokenResponse:
    """Authenticates and returns a signed JWT.

    Raises:
        HTTPException: 401 for any failure. Unknown email, wrong
            password, and a deactivated account are indistinguishable on
            purpose — see auth_service.authenticate.
    """
    try:
        token = authenticate(body.email, body.password)
    except AuthenticationError as err:
        raise HTTPException(status_code=401, detail="invalid email or password") from err
    return TokenResponse(access_token=token)


@router.get(
    "/me",
    response_model=CurrentUserOut,
    responses={
        401: {"description": "Missing/malformed/expired/tampered token, or the account has since been "
              "deactivated — current_user re-reads is_active on every call."},
    },
)
def me(employee: Employee = Depends(current_user)) -> CurrentUserOut:
    """Returns the authenticated employee's basic info."""
    return CurrentUserOut(
        id=employee.id,
        first_name=employee.first_name,
        last_name=employee.last_name,
        email=employee.email,
        role=employee.role,
    )
