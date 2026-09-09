"""Routes for /expertise."""

from fastapi import APIRouter

from app.schemas.expertise import ExpertiseOut
from app.services import expertise_service as service

router = APIRouter(prefix="/expertise", tags=["expertise"])


@router.get("", response_model=list[ExpertiseOut])
def list_expertise() -> list[ExpertiseOut]:
    """Returns every expertise value."""
    return service.list_expertise()
