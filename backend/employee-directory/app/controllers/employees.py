"""Routes for /employees."""

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import current_user, require_role
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.employee import EmployeeCreate, EmployeeOut, EmployeeUpdate
from app.schemas.project import ProjectAssignmentOut, ProjectAssignmentUpdate, ProjectAttach
from app.schemas.skill import SkillAttach, SkillOut
from app.services import employee_service as service
from app.services import project_service, skill_service

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get(
    "",
    response_model=list[EmployeeOut],
    responses={401: {"description": "Not authenticated."}},
)
def list_employees(
    q: str | None = Query(default=None),
    location_id: int | None = Query(default=None),
    expertise_id: int | None = Query(default=None),
    manager_id: int | None = Query(default=None),
    team_id: int | None = Query(default=None),
    department_id: int | None = Query(default=None),
    skill_id: int | None = Query(default=None),
    project_id: int | None = Query(default=None),
    available: bool | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    _employee: Employee = Depends(current_user),
) -> list[EmployeeOut]:
    """Any authenticated employee can search/list employees."""
    return service.list_employees(
        q=q,
        location_id=location_id,
        expertise_id=expertise_id,
        manager_id=manager_id,
        team_id=team_id,
        department_id=department_id,
        skill_id=skill_id,
        project_id=project_id,
        available=available,
        include_inactive=include_inactive,
    )


@router.get(
    "/{employee_id}",
    response_model=EmployeeOut,
    responses={
        401: {"description": "Not authenticated."},
        410: {"description": "No employee with this id."},
    },
)
def get_employee(employee_id: int, _employee: Employee = Depends(current_user)) -> EmployeeOut:
    """Any authenticated employee can look up an employee by id."""
    return service.get_employee(employee_id)


@router.get(
    "/{employee_id}/reports",
    response_model=list[EmployeeOut],
    responses={401: {"description": "Not authenticated."}},
)
def get_reports(employee_id: int, _employee: Employee = Depends(current_user)) -> list[EmployeeOut]:
    """Direct reports — everyone whose manager_id is this id."""
    return service.get_reports(employee_id)


@router.post(
    "",
    response_model=EmployeeOut,
    status_code=201,
    responses={
        201: {"description": "Created."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't Admin (literally Admin — not CEO-or-Admin)."},
        409: {"description": "An employee with this email (any case) already exists."},
        422: {"description": "A field failed validation (e.g. empty name, role other than EMPLOYEE/ADMIN — "
              "MANAGER/CEO are never directly settable, see the teams README section), or work_location_id/"
              "expertise_id doesn't reference an existing row (field named in the response)."},
    },
)
def create_employee(body: EmployeeCreate, _employee: Employee = Depends(require_role(Role.ADMIN))) -> EmployeeOut:
    """Admin only — literally: not CEO-or-Admin, Admin."""
    return service.create_employee(body)


@router.put(
    "/{employee_id}",
    response_model=EmployeeOut,
    responses={
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't allowed to touch a field they submitted — see "
              "employee_service.update_employee for the full self/manager/Admin split."},
        409: {"description": "team_id was submitted for someone who currently manages an active team (use "
              "PUT /teams instead), or a role change would leave an active team without its manager."},
        410: {"description": "No employee with this id, or (for team_id) no team with that id."},
        422: {"description": "A field failed validation, or team_id names a team that exists but is inactive "
              "(field named in the response)."},
    },
)
def update_employee(employee_id: int, body: EmployeeUpdate, actor: Employee = Depends(current_user)) -> EmployeeOut:
    """Self edits their own first_name/last_name/phone; Admin edits
    role (for anyone, including themselves). See
    employee_service.update_employee for the exact authorization split.
    """
    return service.update_employee(actor, employee_id, body)


@router.delete(
    "/{employee_id}",
    response_model=EmployeeOut,
    responses={
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't Admin."},
        409: {"description": "The employee is the CEO, is the last active Admin, or has active direct "
              "reports."},
        410: {"description": "No employee with this id."},
    },
)
def delete_employee(employee_id: int, _employee: Employee = Depends(require_role(Role.ADMIN))) -> EmployeeOut:
    """Admin only. Idempotent; blocked by the CEO, the last active
    Admin, or active direct reports.
    """
    return service.delete_employee(employee_id)


@router.get(
    "/{employee_id}/skills",
    response_model=list[SkillOut],
    responses={
        401: {"description": "Not authenticated."},
        410: {"description": "No employee with this id."},
    },
)
def get_employee_skills(employee_id: int, _employee: Employee = Depends(current_user)) -> list[SkillOut]:
    """Any authenticated employee can see what skills this person has."""
    return skill_service.get_employee_skills(employee_id)


@router.post(
    "/{employee_id}/skills",
    response_model=list[SkillOut],
    responses={
        200: {"description": "The employee already had this skill — no-op, current skill list returned."},
        201: {"description": "A new employee_skills link was created (the skill row itself may or may not have been new)."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't self, this employee's team manager, or Admin."},
        409: {"description": "The target employee is inactive."},
        410: {"description": "No employee with this id."},
        422: {"description": "Skill name is empty/whitespace-only, or over the max length."},
    },
)
def attach_skill(
    employee_id: int,
    body: SkillAttach,
    response: Response,
    actor: Employee = Depends(current_user),
) -> list[SkillOut]:
    """Attaches a skill by name — get-or-create, then link. Status code
    is dynamic (200 vs 201), not fixed by the decorator: see
    skill_service.attach_skill for exactly what decides which.
    """
    skills, created = skill_service.attach_skill(actor, employee_id, body.name)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return skills


@router.delete(
    "/{employee_id}/skills/{skill_id}",
    response_model=list[SkillOut],
    responses={
        200: {"description": "Current skill list after detaching (unchanged if the employee didn't have it)."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't self, this employee's team manager, or Admin."},
        410: {"description": "No employee with this id."},
    },
)
def detach_skill(employee_id: int, skill_id: int, actor: Employee = Depends(current_user)) -> list[SkillOut]:
    """Detaches a skill. Always a clean 200, whether or not the employee
    had it — see skill_service.detach_skill for why.
    """
    return skill_service.detach_skill(actor, employee_id, skill_id)


@router.get(
    "/{employee_id}/projects",
    response_model=list[ProjectAssignmentOut],
    responses={
        401: {"description": "Not authenticated."},
        410: {"description": "No employee with this id."},
    },
)
def get_employee_projects(employee_id: int, _employee: Employee = Depends(current_user)) -> list[ProjectAssignmentOut]:
    """Any authenticated employee can see what projects this person has,
    each with its completed_at.
    """
    return project_service.get_employee_projects(employee_id)


@router.post(
    "/{employee_id}/projects",
    response_model=list[ProjectAssignmentOut],
    responses={
        200: {"description": "The employee was already attached to this project — current list returned."},
        201: {"description": "A new employee_projects link was created (the project itself may or may not have been new)."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't self, this employee's team manager, or Admin."},
        409: {"description": "The target employee is inactive."},
        410: {"description": "No employee with this id."},
        422: {"description": "Project name is empty/whitespace-only, or over the max length."},
    },
)
def attach_project(
    employee_id: int,
    body: ProjectAttach,
    response: Response,
    actor: Employee = Depends(current_user),
) -> list[ProjectAssignmentOut]:
    """Attaches a project by name — get-or-create (never sets
    description — see ProjectAttach), then link, optionally setting
    completed_at. Status code is dynamic, same as skills' attach — see
    project_service.attach_project for exactly what decides 200 vs 201.
    """
    projects, created = project_service.attach_project(actor, employee_id, body.name, body.completed_at)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return projects


@router.put(
    "/{employee_id}/projects/{project_id}",
    response_model=list[ProjectAssignmentOut],
    responses={
        200: {"description": "completed_at set (or cleared — reopened)."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't self, this employee's team manager, or Admin."},
        409: {"description": "The target employee is inactive."},
        410: {"description": "No employee with this id, or no project with this id."},
    },
)
def update_project_completion(
    employee_id: int, project_id: int, body: ProjectAssignmentUpdate, actor: Employee = Depends(current_user)
) -> list[ProjectAssignmentOut]:
    """Sets or clears (reopens) completed_at. Upserts — attaches the
    project first if the employee wasn't already on it; see
    project_service.update_completion.
    """
    return project_service.update_completion(actor, employee_id, project_id, body.completed_at)


@router.delete(
    "/{employee_id}/projects/{project_id}",
    response_model=list[ProjectAssignmentOut],
    responses={
        200: {"description": "Current project list after detaching (unchanged if the employee didn't have it)."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't self, this employee's team manager, or Admin."},
        410: {"description": "No employee with this id."},
    },
)
def detach_project(employee_id: int, project_id: int, actor: Employee = Depends(current_user)) -> list[ProjectAssignmentOut]:
    """Detaches a project. Always a clean 200, whether or not the
    employee had it — see project_service.detach_project for why.
    """
    return project_service.detach_project(actor, employee_id, project_id)
