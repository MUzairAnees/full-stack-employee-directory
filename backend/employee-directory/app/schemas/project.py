"""API schemas for projects."""

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.schemas.common import NonEmptyName, OptionalTrimmedText


class ProjectOut(BaseModel):
    """A project as returned by GET /projects — no completed_at, that's
    a property of an assignment, not the project itself (see
    ProjectAssignmentOut).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None


class ProjectCreate(BaseModel):
    """POST /projects request body — explicit create, open to any
    authenticated user. 409s on a name collision (case-insensitive) —
    unlike attaching (POST /employees/{id}/projects), which is
    get-or-create and never touches description, this is the one place
    allowed to set it, and it does so only at creation: an existing
    project's description isn't silently overwritten by re-POSTing the
    same name (see ProjectUpdate for the Admin-only, explicit way to
    change it).
    """

    name: NonEmptyName
    description: OptionalTrimmedText = None


class ProjectUpdate(BaseModel):
    """PUT /projects/{id} request body — Admin only. Renames and/or
    redescribes an existing project; name collisions (case-insensitive)
    are still a 409, same as create.
    """

    name: NonEmptyName | None = None
    description: OptionalTrimmedText = None


class ProjectAssignmentOut(BaseModel):
    """A project as attached to one employee — returned by
    GET/POST/PUT/DELETE .../employees/{id}/projects[...], always as the
    employee's current full list rather than a single row (same
    convention as skills).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    completed_at: date | None


class ProjectAttach(BaseModel):
    """POST /employees/{id}/projects request body — attach by name,
    get-or-create (no description — see ProjectCreate's docstring for
    why). completed_at is optional: omitted means "in progress" (NULL);
    a caller recording an already-finished project can set it at attach
    time instead of a separate PUT.
    """

    name: NonEmptyName
    completed_at: date | None = None


class ProjectAssignmentUpdate(BaseModel):
    """PUT /employees/{id}/projects/{project_id} request body — sets or
    clears completed_at for an existing (or upserted — see
    project_service) assignment. Required, not optional-with-default:
    this endpoint's only job is setting this one field, including
    explicitly to null to reopen a completed project.
    """

    completed_at: date | None
