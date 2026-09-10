"""Routes for /teams."""

from fastapi import APIRouter, Depends, Query

from app.dependencies import current_user, require_role
from app.models.role import Role
from app.schemas.team import AchievementOut, TeamCreate, TeamOut, TeamUpdate
from app.services import team_service as service

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get(
    "",
    response_model=list[TeamOut],
    responses={401: {"description": "Not authenticated."}},
)
def list_teams(
    department_id: int | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    _employee=Depends(current_user),
) -> list[TeamOut]:
    """Any authenticated employee can list teams."""
    return service.list_teams(department_id=department_id, include_inactive=include_inactive)


@router.get(
    "/{team_id}",
    response_model=TeamOut,
    responses={
        401: {"description": "Not authenticated."},
        410: {"description": "No team with this id."},
    },
)
def get_team(team_id: int, _employee=Depends(current_user)) -> TeamOut:
    """Any authenticated employee can look up a team by id.

    Raises:
        NotFoundError: translated to 410 if no team has that id — active
            or not; only the list hides inactive rows.
    """
    return service.get_team(team_id)


@router.post(
    "",
    response_model=TeamOut,
    status_code=201,
    responses={
        201: {"description": "Created; the nominee is now MANAGER of this team."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't CEO."},
        409: {"description": "The nominee isn't eligible (role isn't EMPLOYEE, or already assigned to a "
              "different team), or the team name collides within the department."},
        422: {"description": "department_id or manager_id doesn't reference an existing row, or department_id "
              "references a soft-deleted department (field named in the response)."},
    },
)
def create_team(body: TeamCreate, _employee=Depends(require_role(Role.CEO))) -> TeamOut:
    """CEO only. Atomically creates the team and promotes the nominated
    employee to MANAGER — see team_service/team_repository for the full
    set of guards on who can be nominated.
    """
    return service.create_team(body)


@router.put(
    "/{team_id}",
    response_model=TeamOut,
    responses={
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't CEO."},
        409: {"description": "The replacement isn't eligible, or the new name collides within the "
              "(possibly new) department."},
        410: {"description": "No team with this id."},
        422: {"description": "department_id or manager_id doesn't reference an existing row, or department_id "
              "references a soft-deleted department (field named in the response)."},
    },
)
def update_team(team_id: int, body: TeamUpdate, _employee=Depends(require_role(Role.CEO))) -> TeamOut:
    """CEO only. Renames, moves to another department, and/or replaces
    the manager — see team_repository.update_team for the full
    promote/demote/bulk-reassignment a manager replacement triggers.
    """
    return service.update_team(team_id, body)


@router.delete(
    "/{team_id}",
    response_model=TeamOut,
    responses={
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't CEO."},
        409: {"description": "Active members other than the manager remain."},
        410: {"description": "No team with this id."},
    },
)
def delete_team(team_id: int, _employee=Depends(require_role(Role.CEO))) -> TeamOut:
    """CEO only. Soft-deletes a team and releases its manager to the
    pool. Idempotent. Blocked while active members other than the
    manager remain — see team_repository.soft_delete_team.
    """
    return service.delete_team(team_id)


@router.get(
    "/{team_id}/achievements",
    response_model=list[AchievementOut],
    responses={
        401: {"description": "Not authenticated."},
        410: {"description": "No team with this id."},
        422: {"description": "month is present but not in YYYY-MM form."},
    },
)
def get_team_achievements(
    team_id: int,
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    _employee=Depends(current_user),
) -> list[AchievementOut]:
    """Completed projects (completed_at IS NOT NULL) for this team's
    current active members. month ("YYYY-MM") narrows to that month;
    omitted returns all-time completions — answers both "what shipped in
    March" and "total done ever". See team_repository.get_team_achievements
    for the attribution caveats (current membership only, active only).
    """
    return service.get_achievements(team_id, month)
