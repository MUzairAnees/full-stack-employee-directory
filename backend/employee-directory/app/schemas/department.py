"""API schemas for departments."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.common import NonEmptyName


class DepartmentOut(BaseModel):
    """A department as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DepartmentCreate(BaseModel):
    """POST /departments request body."""

    name: NonEmptyName


class DepartmentUpdate(BaseModel):
    """PUT /departments/{id} request body.

    is_active can only ever be True (a restore) here, never False — a
    real type constraint, not a hand-raised business rule, so FastAPI
    rejects False with a genuine validation error (free 422, documented
    in the OpenAPI schema) before this ever reaches the service layer.
    Deactivating is DELETE's job, which runs the empty-department guard;
    letting PUT do it too would bypass that guard entirely.
    """

    name: NonEmptyName | None = None
    is_active: Literal[True] | None = None

    @field_validator("is_active", mode="before")
    @classmethod
    def _reject_deactivate_via_put(cls, value: object) -> object:
        if value is False:
            raise ValueError("is_active cannot be set to false here - use DELETE to deactivate")
        return value
