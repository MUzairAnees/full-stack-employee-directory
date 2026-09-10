"""API schemas for teams."""

from datetime import datetime

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
