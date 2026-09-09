"""Work location row model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class WorkLocation:
    """A physical or logical work location (e.g. an office, or "Remote")."""

    id: int
    name: str
    address_line_1: str | None
    city: str | None
    state: str | None
    zip: str | None
    created_at: datetime
    updated_at: datetime
