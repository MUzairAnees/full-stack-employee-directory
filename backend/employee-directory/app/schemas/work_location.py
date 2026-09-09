"""API response schema for work locations."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WorkLocationOut(BaseModel):
    """A work location as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address_line_1: str | None
    city: str | None
    state: str | None
    zip: str | None
    created_at: datetime
    updated_at: datetime
