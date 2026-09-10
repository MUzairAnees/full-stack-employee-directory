"""API schemas for employees."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.role import Role
from app.schemas.common import NonEmptyName, OptionalTrimmedText


class EmployeeOut(BaseModel):
    """An employee as returned by the API. Never includes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    email: str
    phone: str | None
    role: str
    work_location_id: int
    team_id: int | None
    manager_id: int | None
    expertise_id: int
    project_availability: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EmployeeCreate(BaseModel):
    """POST /employees request body (Admin only).

    manager_id is deliberately absent — it's derived by the system,
    never accepted as input (see app/models/employee.py and
    employee_repository._compute_manager_id). team_id is absent too:
    team assignment isn't a capability that exists yet (slice 5).
    """

    first_name: NonEmptyName
    last_name: NonEmptyName
    email: str
    password: str
    role: Role
    work_location_id: int
    expertise_id: int
    phone: OptionalTrimmedText = None
    project_availability: bool = True


class EmployeeUpdate(BaseModel):
    """PUT /employees/{id} request body.

    Which fields a given caller may actually set is enforced in
    employee_service.update_employee, not here — the schema just
    describes the shape:
      - first_name/last_name/phone: self only ("contact info" this
        slice — see README)
      - role: Admin only, for any target including themselves
    manager_id is never on this schema — see EmployeeCreate.
    """

    first_name: NonEmptyName | None = None
    last_name: NonEmptyName | None = None
    phone: OptionalTrimmedText = None
    role: Role | None = None
