"""Business logic for work locations. Read-only in this slice."""

from app.models.work_location import WorkLocation
from app.repositories import work_location_repository as repo


def list_work_locations() -> list[WorkLocation]:
    """Returns every work location.

    Returns:
        list[WorkLocation]: All work locations.
    """
    return repo.list_work_locations()


def get_work_location(location_id: int) -> WorkLocation:
    """Returns a single work location.

    Args:
        location_id: The work location's id.

    Returns:
        WorkLocation: The matching work location.

    Raises:
        NotFoundError: If no work location has that id.
    """
    return repo.get_work_location(location_id)
