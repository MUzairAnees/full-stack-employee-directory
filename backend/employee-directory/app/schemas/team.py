"""API schemas for teams."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import NonEmptyName


class TeamOut(BaseModel):
    """A team as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    department_id: int
    manager_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TeamCreate(BaseModel):
    """POST /teams request body (CEO only).

    manager_id here is a NOMINATION, not an assignment of an existing
    manager — the nominee must currently hold role EMPLOYEE with no
    team; team_repository.create_team overwrites their role to MANAGER
    as part of this operation (see slice 5 section 1). It is not the
    same kind of field as employees.manager_id, which is always derived
    and never accepted as input anywhere.
    """

    name: NonEmptyName
    department_id: int
    manager_id: int


class TeamUpdate(BaseModel):
    """PUT /teams/{id} request body (CEO only). All fields optional —
    only the ones submitted are changed. A submitted manager_id names
    the REPLACEMENT manager; see team_repository.update_team for the
    full promote/demote/bulk-reassignment this triggers, and for the
    no-op case where it names the team's current manager.
    """

    name: NonEmptyName | None = None
    manager_id: int | None = None
    department_id: int | None = None


class AchievementOut(BaseModel):
    """One completed project, from GET /teams/{id}/achievements.

    Attribution is CURRENT-team-membership-only — there's no historical
    team-assignment record, so a completion is credited to whoever is on
    the team now, not who was on it when the project was completed. Also
    active-employees-only, stacking on that same caveat: someone who
    left takes their completions out of their former team's total. Both
    stated together in the backend README as one limitation, not two.
    """

    model_config = ConfigDict(from_attributes=True)

    employee_id: int
    employee_first_name: str
    employee_last_name: str
    project_id: int
    project_name: str
    completed_at: date
