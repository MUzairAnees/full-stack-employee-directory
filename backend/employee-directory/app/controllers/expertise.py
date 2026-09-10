"""Routes for /expertise."""

from fastapi import APIRouter, Depends

from app.dependencies import current_user
from app.models.employee import Employee
from app.schemas.expertise import ExpertiseOut
from app.services import expertise_service as service

router = APIRouter(prefix="/expertise", tags=["expertise"])


@router.get(
    "",
    response_model=list[ExpertiseOut],
    responses={401: {"description": "Not authenticated."}},
)
def list_expertise(_employee: Employee = Depends(current_user)) -> list[ExpertiseOut]:
    """Returns every expertise value. Requires authentication — same gap
    and same fix as /work-locations (see that controller's docstring):
    this was also slice 1 code, also written before auth existed, also
    never revisited. Not explicitly named in the slice 4 ask, but the
    stated reasoning applies word for word, so fixed alongside it rather
    than left inconsistent on a technicality.
    """
    return service.list_expertise()
