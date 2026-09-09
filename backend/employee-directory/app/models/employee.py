"""Employee row model.

Auth-relevant fields only for this slice — extended as later slices need
more (skills, projects, manager, etc.).
"""

from dataclasses import dataclass


@dataclass
class Employee:
    """An employee, as needed for login and current_user resolution."""

    id: int
    first_name: str
    last_name: str
    email: str
    password_hash: str
    role: str
    is_active: bool
