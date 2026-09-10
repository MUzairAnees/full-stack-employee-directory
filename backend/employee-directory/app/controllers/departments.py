"""Routes for /departments."""

from fastapi import APIRouter, Depends, Query

from app.dependencies import current_user, require_role
from app.models.role import Role
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services import department_service as service

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get(
    "",
    response_model=list[DepartmentOut],
    responses={401: {"description": "Not authenticated."}},
)
def list_departments(
    include_inactive: bool = Query(default=False),
    _employee=Depends(current_user),
) -> list[DepartmentOut]:
    """Any authenticated employee can list departments."""
    return service.list_departments(include_inactive=include_inactive)


@router.get(
    "/{department_id}",
    response_model=DepartmentOut,
    responses={
        401: {"description": "Not authenticated."},
        410: {"description": "No department with this id."},
    },
)
def get_department(department_id: int, _employee=Depends(current_user)) -> DepartmentOut:
    """Any authenticated employee can look up a department by id.

    Raises:
        NotFoundError: translated to 410 Gone if no department has that
            id — active or not; only the list hides inactive rows.
    """
    return service.get_department(department_id)


@router.post(
    "",
    response_model=DepartmentOut,
    status_code=201,
    responses={
        201: {"description": "Created."},
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't CEO."},
        409: {"description": "A department with this name already exists (including a soft-deleted one — "
              "soft delete keeps the name)."},
        422: {"description": "Name is empty/whitespace-only or over the max length."},
    },
)
def create_department(body: DepartmentCreate, _employee=Depends(require_role(Role.CEO))) -> DepartmentOut:
    """CEO only.

    Raises:
        DuplicateError: translated to 409 if the name is already taken
            (including by a soft-deleted department).
    """
    return service.create_department(body.name)


@router.put(
    "/{department_id}",
    response_model=DepartmentOut,
    responses={
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't CEO."},
        409: {"description": "The new name is already taken."},
        410: {"description": "No department with this id."},
        422: {"description": "Name is empty/whitespace-only/over the max length, or is_active was submitted "
              "as false (PUT can only ever restore, never deactivate — that's what DELETE is for)."},
    },
)
def update_department(
    department_id: int, body: DepartmentUpdate, _employee=Depends(require_role(Role.CEO))
) -> DepartmentOut:
    """CEO only. Renames and/or restores (is_active: true) a department.

    Raises:
        NotFoundError: translated to 410 if no department has that id.
        DuplicateError: translated to 409 if the new name is taken.
    """
    return service.update_department(department_id, body.name, body.is_active)


@router.delete(
    "/{department_id}",
    response_model=DepartmentOut,
    responses={
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't CEO."},
        409: {"description": "The department has active employees (through its teams) and isn't already "
              "inactive."},
        410: {"description": "No department with this id."},
    },
)
def delete_department(department_id: int, _employee=Depends(require_role(Role.CEO))) -> DepartmentOut:
    """CEO only. Soft-deletes a department. Idempotent: deleting an
    already-inactive department just returns it (200), not a fresh 409.

    Raises:
        NotFoundError: translated to 410 if no department has that id.
        DependentsExistError: translated to 409 if it has any active
            employee (through teams) and isn't already inactive.
    """
    return service.delete_department(department_id)
