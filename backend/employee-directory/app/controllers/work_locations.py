"""Routes for /work-locations."""

from fastapi import APIRouter, Depends

from app.dependencies import current_user
from app.models.employee import Employee
from app.schemas.work_location import WorkLocationOut
from app.services import work_location_service as service

router = APIRouter(prefix="/work-locations", tags=["work-locations"])


@router.get(
    "",
    response_model=list[WorkLocationOut],
    responses={401: {"description": "Not authenticated."}},
)
def list_work_locations(_employee: Employee = Depends(current_user)) -> list[WorkLocationOut]:
    """Returns every work location. Requires authentication — this was
    slice 1 code, written before auth existed in slice 2, and nothing
    went back to add the dependency the other GETs use. The data isn't
    sensitive; the inconsistency (a stranger with the CloudFront URL
    could curl this with no token) was the problem.
    """
    return service.list_work_locations()


@router.get(
    "/{location_id}",
    response_model=WorkLocationOut,
    responses={
        401: {"description": "Not authenticated."},
        410: {"description": "No work location with this id."},
        422: {"description": "location_id is not an integer."},
    },
)
def get_work_location(location_id: int, _employee: Employee = Depends(current_user)) -> WorkLocationOut:
    """Returns a single work location by id.

    Raises:
        NotFoundError: translated to 410 Gone by the app-level exception
            handler (see app/main.py) if no work location has that id.
    """
    return service.get_work_location(location_id)
