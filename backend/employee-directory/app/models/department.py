"""Department row model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Department:
    """A department. Reached directly, not through a team — teams point
    to departments (department_id), not the other way around.
    """

    id: int
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
