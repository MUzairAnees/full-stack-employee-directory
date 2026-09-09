"""Business logic for expertise. Read-only in this slice."""

from app.models.expertise import Expertise
from app.repositories import expertise_repository as repo


def list_expertise() -> list[Expertise]:
    """Returns every expertise value.

    Returns:
        list[Expertise]: All expertise values.
    """
    return repo.list_expertise()
