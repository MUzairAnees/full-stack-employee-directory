"""API schemas for authentication."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """POST /login request body."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """POST /login response body."""

    access_token: str
    token_type: str = "bearer"


class CurrentUserOut(BaseModel):
    """GET /me response body."""

    id: int
    first_name: str
    last_name: str
    email: str
    role: str
