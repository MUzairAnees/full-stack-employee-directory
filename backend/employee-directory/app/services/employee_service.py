"""Business logic for employees."""

import bcrypt
from fastapi import HTTPException

from app.config import BCRYPT_ROUNDS
from app.models.employee import Employee
from app.models.role import Role
from app.repositories import employee_repository as repo
from app.schemas.employee import EmployeeCreate, EmployeeUpdate


def list_employees(
    *,
    q: str | None = None,
    location_id: int | None = None,
    expertise_id: int | None = None,
    manager_id: int | None = None,
    team_id: int | None = None,
    department_id: int | None = None,
    available: bool | None = None,
    include_inactive: bool = False,
) -> list[Employee]:
    return repo.list_employees(
        q=q,
        location_id=location_id,
        expertise_id=expertise_id,
        manager_id=manager_id,
        team_id=team_id,
        department_id=department_id,
        available=available,
        include_inactive=include_inactive,
    )


def get_employee(employee_id: int) -> Employee:
    return repo.get_employee(employee_id)


def get_reports(employee_id: int) -> list[Employee]:
    return repo.get_reports(employee_id)


def create_employee(body: EmployeeCreate) -> Employee:
    """Admin only (enforced by the controller's require_role). Hashes
    the password with the one shared cost factor (app.config), and
    normalizes email the same way login does — the LOWER(email) unique
    index stops two rows differing only by case, but does nothing to
    stop ONE row being stored mixed-case in the first place, which the
    case-insensitive lookup could then still fail to find if this ever
    skipped normalizing.
    """
    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()
    return repo.create_employee(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password_hash=password_hash,
        role=body.role,
        work_location_id=body.work_location_id,
        expertise_id=body.expertise_id,
        phone=body.phone,
        project_availability=body.project_availability,
    )


def update_employee(actor: Employee, target_id: int, update: EmployeeUpdate) -> Employee:
    """Authorization split, enforced here rather than in the repository:
      - self may set first_name/last_name/phone — "contact info" this
        slice (see README)
      - Admin may set role, for anyone including themselves
      - nothing else is permitted, regardless of who's asking

    Raises:
        HTTPException: 403 if the caller isn't allowed to touch the
            field(s) they submitted.
    """
    target = repo.get_employee(target_id)
    is_self = actor.id == target.id
    is_admin = actor.role == Role.ADMIN

    if not is_self and not is_admin:
        raise HTTPException(status_code=403, detail="you don't have permission")

    touching_identity = (
        update.first_name is not None or update.last_name is not None or "phone" in update.model_fields_set
    )
    if touching_identity and not is_self:
        raise HTTPException(status_code=403, detail="you can only edit your own contact info")

    if update.role is not None and not is_admin:
        raise HTTPException(status_code=403, detail="only Admin can change role")

    # UNSET, not None, when phone wasn't in the request at all — None
    # would mean "clear it", which is a real, different instruction.
    phone_value = update.phone if "phone" in update.model_fields_set else repo.UNSET

    return repo.update_employee(
        target_id,
        first_name=update.first_name,
        last_name=update.last_name,
        phone=phone_value,
        role=update.role,
    )


def delete_employee(employee_id: int) -> Employee:
    return repo.soft_delete_employee(employee_id)
