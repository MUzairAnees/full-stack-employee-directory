"""Business logic for teams. All writes are CEO-only, enforced in the
controller via require_role — nothing here branches on who's asking, so
unlike employee_service there's no authorization split to encode.
"""

from app.models.team import Team
from app.repositories import team_repository as repo
from app.schemas.team import TeamCreate, TeamUpdate


def list_teams(*, department_id: int | None = None, include_inactive: bool = False) -> list[Team]:
    return repo.list_teams(department_id=department_id, include_inactive=include_inactive)


def get_team(team_id: int) -> Team:
    return repo.get_team(team_id)


def create_team(body: TeamCreate) -> Team:
    return repo.create_team(name=body.name, department_id=body.department_id, manager_id=body.manager_id)


def update_team(team_id: int, body: TeamUpdate) -> Team:
    return repo.update_team(
        team_id,
        name=body.name,
        manager_id=body.manager_id,
        department_id=body.department_id,
    )


def delete_team(team_id: int) -> Team:
    return repo.soft_delete_team(team_id)
