"""API schemas for skills."""

from pydantic import BaseModel, ConfigDict

from app.schemas.common import NonEmptyName


class SkillOut(BaseModel):
    """A skill as returned by the API — from the lookup list
    (GET /skills) or an employee's own skills (GET /employees/{id}/skills
    and the attach/detach responses, which return the employee's current
    list rather than a single row — see app/controllers/employees.py).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class SkillAttach(BaseModel):
    """POST /employees/{id}/skills request body — attach by name,
    get-or-create. Reuses NonEmptyName: strip, min_length, max_length,
    same as every other name field in this app.
    """

    name: NonEmptyName
