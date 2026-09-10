"""Routes for /skills — the shared lookup list. Per-employee attach/
detach lives under /employees/{id}/skills (app/controllers/employees.py),
since those are employee sub-resources, not skill ones.
"""

from fastapi import APIRouter, Depends

from app.dependencies import current_user
from app.models.employee import Employee
from app.schemas.skill import SkillOut
from app.services import skill_service as service

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get(
    "",
    response_model=list[SkillOut],
    responses={401: {"description": "Not authenticated."}},
)
def list_skills(_employee: Employee = Depends(current_user)) -> list[SkillOut]:
    """Any authenticated employee can list the full skills lookup."""
    return service.list_skills()
