"""Routes for /employees."""

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import current_user, require_role
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.employee import EmployeeCreate, EmployeeOut, EmployeeUpdate
from app.schemas.skill import SkillAttach, SkillOut
from app.services import employee_service as service
from app.services import skill_service

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    q: str | None = Query(default=None),
    location_id: int | None = Query(default=None),
    expertise_id: int | None = Query(default=None),
    manager_id: int | None = Query(default=None),
    team_id: int | None = Query(default=None),
    department_id: int | None = Query(default=None),
    skill_id: int | None = Query(default=None),
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
        available=available,
        include_inactive=include_inactive,
    )


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int, _employee: Employee = Depends(current_user)) -> EmployeeOut:
    """Any authenticated employee can look up an employee by id."""
    return service.get_employee(employee_id)


@router.get("/{employee_id}/reports", response_model=list[EmployeeOut])
def get_reports(employee_id: int, _employee: Employee = Depends(current_user)) -> list[EmployeeOut]:
    """Direct reports — everyone whose manager_id is this id."""
    return service.get_reports(employee_id)


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(body: EmployeeCreate, _employee: Employee = Depends(require_role(Role.ADMIN))) -> EmployeeOut:
    """Admin only — literally: not CEO-or-Admin, Admin."""
    return service.create_employee(body)


@router.put("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, body: EmployeeUpdate, actor: Employee = Depends(current_user)) -> EmployeeOut:
    """Self edits their own first_name/last_name/phone; Admin edits
    role (for anyone, including themselves). See
    employee_service.update_employee for the exact authorization split.
    """
    return service.update_employee(actor, employee_id, body)


@router.delete("/{employee_id}", response_model=EmployeeOut)
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
