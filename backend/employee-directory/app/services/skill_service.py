"""Business logic for skills — the shared lookup list, and attaching/
detaching per employee.

Authorization on attach/detach reuses employee_service.authorization_context
(self / manager-of-target's-team / Admin) — the same split slice 5 built
for PUT /employees, not a second copy. Deliberately NOT CEO: consistent
with the CEO having no general employee-editing power anywhere in this
app.
"""

from fastapi import HTTPException

from app.exceptions import DependentsExistError
from app.models.employee import Employee
from app.models.skill import Skill
from app.repositories import employee_repository, skill_repository
from app.services.employee_service import authorization_context


def list_skills() -> list[Skill]:
    return skill_repository.list_skills()


def get_employee_skills(employee_id: int) -> list[Skill]:
    """Raises:
    NotFoundError: no such employee (translated to 410).
    """
    employee_repository.get_employee(employee_id)
    return skill_repository.list_employee_skills(employee_id)


def _require_can_edit_skills(actor: Employee, target: Employee) -> None:
    is_self, is_admin, is_manager_of_target = authorization_context(actor, target)
    if not (is_self or is_admin or is_manager_of_target):
        raise HTTPException(status_code=403, detail="you don't have permission to edit this employee's skills")


def attach_skill(actor: Employee, employee_id: int, name: str) -> tuple[list[Skill], bool]:
    """Attaches a skill by name — get-or-create the skill, then link it.

    Rejects an inactive target: attaching creates a NEW row (unlike
    editing an existing field), so there's a real case for "don't create
    new associations against an inactive record" here that doesn't
    (yet) apply anywhere else in this app — see the README/commit notes
    on PUT /employees having no equivalent guard, a known, deliberately
    unresolved inconsistency flagged for a later slice. Detach has no
    such guard: removing data from an inactive record is never harmful.

    Returns:
        tuple[list[Skill], bool]: the employee's current skills, and
        whether a NEW employee_skills row was created (vs. the employee
        already having this skill) — the controller uses the second to
        choose 201 vs 200.

    Raises:
        NotFoundError: no such employee (410).
        HTTPException: 403 if the caller isn't self, this employee's
            team manager, or Admin.
        DependentsExistError: the target employee is inactive (409).
    """
    target = employee_repository.get_employee(employee_id)
    _require_can_edit_skills(actor, target)
    if not target.is_active:
        raise DependentsExistError(f"employee {employee_id} is inactive; cannot attach a skill")

    skill = skill_repository.get_or_create_skill(name)
    created = skill_repository.attach_skill(employee_id, skill.id)
    return skill_repository.list_employee_skills(employee_id), created


def detach_skill(actor: Employee, employee_id: int, skill_id: int) -> list[Skill]:
    """Detaches a skill. Clean success whether or not the employee had
    it — there's no "not found" to report for a join row, and no
    is_active guard (see attach_skill's docstring for why the two
    differ).

    Returns:
        list[Skill]: the employee's current skills after detaching.

    Raises:
        NotFoundError: no such employee (410).
        HTTPException: 403 if the caller isn't self, this employee's
            team manager, or Admin.
    """
    target = employee_repository.get_employee(employee_id)
    _require_can_edit_skills(actor, target)
    skill_repository.detach_skill(employee_id, skill_id)
    return skill_repository.list_employee_skills(employee_id)
