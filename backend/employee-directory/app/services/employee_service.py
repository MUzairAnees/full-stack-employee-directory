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
    skill_id: int | None = None,
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
        skill_id=skill_id,
        available=available,
        include_inactive=include_inactive,
    )


def authorization_context(actor: Employee, target: Employee) -> tuple[bool, bool, bool]:
    """Returns (is_self, is_admin, is_manager_of_target) — the same
    three-way split every field-family check in update_employee below is
    built from, and (as of slice 6) skill_service's attach/detach
    authorization too. Promoted here rather than duplicated, same
    reasoning as compute_manager_id/get_ceo_id in slice 5.

    "manager of target" is checked against the TARGET's CURRENT team_id,
    as the caller already fetched it — not before-or-after: the CEO has
    team_id NULL, so an after-the-fact check would let a manager claim
    the CEO onto their team and then edit them. A manager checking
    against THEMSELVES as target correctly returns True too — not a
    special case, see employee_repository.compute_manager_id/
    team_repository for why a manager's own team_id always equals the
    team they manage.
    """
    is_self = actor.id == target.id
    is_admin = actor.role == Role.ADMIN
    is_manager_of_target = (
        actor.role == Role.MANAGER and actor.team_id is not None and actor.team_id == target.team_id
    )
    return is_self, is_admin, is_manager_of_target


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
    """Authorization, enforced here rather than in the repository — each
    field family gets its own check, and each REJECTS (403) a caller who
    isn't allowed to touch it, rather than silently dropping the field:
    a silently-dropped field returns 200 and leaves the caller believing
    the change saved, which is invisible in testing and confusing in use.

    As of slice 5:
        first_name / last_name / phone          -> self, manager of this
                                                     employee's team, or
                                                     Admin
        work_location_id / project_availability
            / expertise_id                       -> manager of this
                                                     employee's team, or
                                                     Admin (not self)
        role                                      -> Admin
        team_id                                   -> Admin, or manager
                                                     of this employee's
                                                     team (release, null,
                                                     only — placing a
                                                     real value is
                                                     Admin-only)

    "manager of this employee's team" is authorization_context() above —
    see its docstring for why it's checked against the target's CURRENT
    team_id, before any change, and why a manager editing themselves
    correctly counts too.

    The team_id LOCK (an employee who currently manages an active team
    can't have team_id touched by anyone, Admin included) lives in
    employee_repository.update_employee, checked AFTER this function's
    authorization — never reveal a business invariant to a caller who
    had no standing to ask in the first place, the same principle behind
    checking authentication before authorization.

    Raises:
        HTTPException: 403 if the caller isn't allowed to touch the
            field(s) they submitted.
    """
    target = repo.get_employee(target_id)
    is_self, is_admin, is_manager_of_target = authorization_context(actor, target)

    fields_set = update.model_fields_set

    identity_fields = {"first_name", "last_name", "phone"} & fields_set
    if identity_fields and not (is_self or is_manager_of_target or is_admin):
        raise HTTPException(status_code=403, detail="you don't have permission to edit this employee's contact info")

    placement_fields = {"work_location_id", "project_availability", "expertise_id"} & fields_set
    if placement_fields and not (is_manager_of_target or is_admin):
        raise HTTPException(
            status_code=403,
            detail="only this employee's team manager or an Admin can edit work location, availability, or expertise",
        )

    if "role" in fields_set and not is_admin:
        raise HTTPException(status_code=403, detail="only Admin can change role")

    if "team_id" in fields_set:
        if not (is_admin or is_manager_of_target):
            raise HTTPException(
                status_code=403, detail="only Admin or this employee's team manager can change team_id"
            )
        if is_manager_of_target and not is_admin and update.team_id is not None:
            raise HTTPException(
                status_code=403, detail="a manager may only release a team member (team_id to null), not place one"
            )

    # UNSET, not None, when a field wasn't in the request at all — None
    # would mean "clear it", a real, different instruction. Applies to
    # phone (can be cleared) and team_id (can be released to null).
    phone_value = update.phone if "phone" in fields_set else repo.UNSET
    team_id_value = update.team_id if "team_id" in fields_set else repo.UNSET

    return repo.update_employee(
        target_id,
        first_name=update.first_name,
        last_name=update.last_name,
        phone=phone_value,
        role=update.role,
        work_location_id=update.work_location_id,
        project_availability=update.project_availability,
        expertise_id=update.expertise_id,
        team_id=team_id_value,
    )


def delete_employee(employee_id: int) -> Employee:
    return repo.soft_delete_employee(employee_id)
