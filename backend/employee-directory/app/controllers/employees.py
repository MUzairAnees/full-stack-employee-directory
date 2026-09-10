"""Routes for /employees."""

from fastapi import APIRouter, Depends, Query

from app.dependencies import current_user, require_role
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.employee import EmployeeCreate, EmployeeOut, EmployeeUpdate
from app.services import employee_service as service

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    q: str | None = Query(default=None),
    location_id: int | None = Query(default=None),
    expertise_id: int | None = Query(default=None),
    manager_id: int | None = Query(default=None),
    team_id: int | None = Query(default=None),
    department_id: int | None = Query(default=None),
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
