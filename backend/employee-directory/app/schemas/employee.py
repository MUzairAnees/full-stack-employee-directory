"""API schemas for employees."""

from datetime import datetime
from typing import Literal

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

    role is restricted to EMPLOYEE/ADMIN — slice 5 section 0: MANAGER is
    a role conferred by team assignment (POST/PUT /teams) and by nothing
    else, never pre-set; CEO is single and seeded, never created. This
    Literal makes any other value a 422 at the schema layer, before any
    of our own code runs, rather than relying on the DB's
    idx_employees_one_active_ceo to reject a second CEO after the fact.

    manager_id is deliberately absent — it's derived by the system,
    never accepted as input (see app/models/employee.py and
    employee_repository.compute_manager_id). team_id is absent too: team
    assignment isn't a capability POST /employees has, ever — a MANAGER
    can now never exist without a team as a direct structural
    consequence of role being restricted here.
    """

    first_name: NonEmptyName
    last_name: NonEmptyName
    email: str
    password: str
    role: Literal[Role.EMPLOYEE, Role.ADMIN]
    work_location_id: int
    expertise_id: int
    phone: OptionalTrimmedText = None
    project_availability: bool = True


class EmployeeUpdate(BaseModel):
    """PUT /employees/{id} request body.

    Which fields a given caller may actually set is enforced in
    employee_service.update_employee, not here — the schema just
    describes the shape. As of slice 5, the RBAC table is:

        first_name / last_name / phone            -> self, manager of
                                                       this employee's
                                                       team, or Admin
        work_location_id / project_availability
            / expertise_id                          -> manager of this
                                                       employee's team,
                                                       or Admin
        role                                        -> Admin
        team_id                                     -> Admin (any valid
                                                       active team, or
                                                       null); manager of
                                                       this employee's
                                                       team (null only —
                                                       release, never
                                                       place). LOCKED
                                                       entirely — for
                                                       every caller,
                                                       Admin included —
                                                       while the TARGET
                                                       manages an active
                                                       team; the only
                                                       path that moves a
                                                       team's manager is
                                                       PUT /teams.

    role is restricted the same way as EmployeeCreate — MANAGER/CEO
    can't be set directly here either, same section-0 reasoning: there
    is no direct promotion, same as there is no direct demotion (the
    existing role-change guard in employee_repository.update_employee
    now always fires for a current MANAGER, since that role no longer
    exists without an active team to go with it).

    manager_id is never on this schema — see EmployeeCreate. team_id
    uses plain int | None (NOT a Literal[None]-style "one legal value"
    type like department's is_active): unlike that field, this
    restriction is role-dependent, not universal — Admin must be able to
    place someone into a real team, a Manager may only release (null).
    A role-dependent restriction can't live in the type; it's enforced
    in the service.
    """

    first_name: NonEmptyName | None = None
    last_name: NonEmptyName | None = None
    phone: OptionalTrimmedText = None
    role: Literal[Role.EMPLOYEE, Role.ADMIN] | None = None
    work_location_id: int | None = None
    project_availability: bool | None = None
    expertise_id: int | None = None
    team_id: int | None = None
