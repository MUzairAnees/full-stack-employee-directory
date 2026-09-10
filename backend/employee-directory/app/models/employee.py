"""Employee row model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Employee:
    """An employee. manager_id is derived by the system (see
    employee_repository._compute_manager_id) — never set directly by a
    caller, so it never appears on a request schema.
    """

    id: int
    first_name: str
    last_name: str
    email: str
    phone: str | None
    password_hash: str
    role: str
    work_location_id: int
    team_id: int | None
    manager_id: int | None
    expertise_id: int
    project_availability: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
