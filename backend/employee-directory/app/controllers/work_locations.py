"""Routes for /work-locations."""

from fastapi import APIRouter

from app.schemas.work_location import WorkLocationOut
from app.services import work_location_service as service

router = APIRouter(prefix="/work-locations", tags=["work-locations"])


@router.get("", response_model=list[WorkLocationOut])
def list_work_locations() -> list[WorkLocationOut]:
    """Returns every work location."""
    return service.list_work_locations()


@router.get("/{location_id}", response_model=WorkLocationOut)
def get_work_location(location_id: int) -> WorkLocationOut:
    """Returns a single work location by id.

    Raises:
        NotFoundError: translated to 410 Gone by the app-level exception
            handler (see app/main.py) if no work location has that id.
    """
    return service.get_work_location(location_id)
