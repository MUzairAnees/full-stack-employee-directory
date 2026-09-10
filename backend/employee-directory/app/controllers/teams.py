"""Routes for /teams."""

from fastapi import APIRouter, Depends, Query

from app.dependencies import current_user, require_role
from app.models.role import Role
from app.schemas.team import TeamCreate, TeamOut, TeamUpdate
from app.services import team_service as service

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamOut])
def list_teams(
    department_id: int | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    _employee=Depends(current_user),
) -> list[TeamOut]:
    """Any authenticated employee can list teams."""
    return service.list_teams(department_id=department_id, include_inactive=include_inactive)


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: int, _employee=Depends(current_user)) -> TeamOut:
    """Any authenticated employee can look up a team by id.

    Raises:
        NotFoundError: translated to 410 if no team has that id — active
            or not; only the list hides inactive rows.
    """
    return service.get_team(team_id)


@router.post("", response_model=TeamOut, status_code=201)
def create_team(body: TeamCreate, _employee=Depends(require_role(Role.CEO))) -> TeamOut:
    """CEO only. Atomically creates the team and promotes the nominated
    employee to MANAGER — see team_service/team_repository for the full
    set of guards on who can be nominated.
    """
    return service.create_team(body)


@router.put("/{team_id}", response_model=TeamOut)
def update_team(team_id: int, body: TeamUpdate, _employee=Depends(require_role(Role.CEO))) -> TeamOut:
    """CEO only. Renames, moves to another department, and/or replaces
    the manager — see team_repository.update_team for the full
    promote/demote/bulk-reassignment a manager replacement triggers.
    """
    return service.update_team(team_id, body)


@router.delete("/{team_id}", response_model=TeamOut)
def delete_team(team_id: int, _employee=Depends(require_role(Role.CEO))) -> TeamOut:
    """CEO only. Soft-deletes a team and releases its manager to the
    pool. Idempotent. Blocked while active members other than the
    manager remain — see team_repository.soft_delete_team.
    """
    return service.delete_team(team_id)
