"""API response schema for expertise."""

from pydantic import BaseModel, ConfigDict


class ExpertiseOut(BaseModel):
    """An expertise value as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
