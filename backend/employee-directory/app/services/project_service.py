"""Business logic for projects — the shared lookup list (explicit
create/update), and attaching/updating-completion/detaching per
employee.

Authorization on the per-employee operations reuses
employee_service.authorization_context (self / manager-of-target's-team
/ Admin) — same split as skills, not a second copy. Deliberately NOT
CEO, same reasoning as skills.
"""

from fastapi import HTTPException

from app.exceptions import DependentsExistError
from app.models.employee import Employee
from app.models.project import Project, ProjectAssignment
from app.repositories import employee_repository, project_repository
from app.schemas.project import ProjectUpdate
from app.services.employee_service import authorization_context


def list_projects() -> list[Project]:
    return project_repository.list_projects()


def get_project(project_id: int) -> Project:
    return project_repository.get_project(project_id)


def create_project(name: str, description: str | None) -> Project:
    """Open to any authenticated user (enforced by the controller's
    current_user, not require_role — no gate here). 409s on a name
    collision rather than merging; see project_repository.create_project.
    """
    return project_repository.create_project(name, description)


def update_project(project_id: int, body: ProjectUpdate) -> Project:
    """Admin only (enforced by the controller's require_role).

    description uses UNSET-vs-provided the same way employee phone/team_id
    do: omitted means leave it alone, explicitly null means clear it —
    distinguished via model_fields_set, not by the value alone (both
    "omitted" and "explicit null" arrive as body.description is None).
    """
    fields_set = body.model_fields_set
    description_value = body.description if "description" in fields_set else project_repository.UNSET
    return project_repository.update_project(project_id, name=body.name, description=description_value)


def get_employee_projects(employee_id: int) -> list[ProjectAssignment]:
    """Raises:
    NotFoundError: no such employee (410).
    """
    employee_repository.get_employee(employee_id)
    return project_repository.list_employee_projects(employee_id)


def _require_can_edit_projects(actor: Employee, target: Employee) -> None:
    is_self, is_admin, is_manager_of_target = authorization_context(actor, target)
    if not (is_self or is_admin or is_manager_of_target):
        raise HTTPException(status_code=403, detail="you don't have permission to edit this employee's projects")


def _require_active_target(employee_id: int, target: Employee) -> None:
    """Guards operations that can create a NEW employee_projects row
    (attach, and completion-update since it upserts) — same reasoning as
    skill_service's inactive-employee guard: creating a new association
    against an inactive record is a different case from editing an
    existing field, which PUT /employees still doesn't guard (README —
    a known, deliberately deferred inconsistency).
    """
    if not target.is_active:
        raise DependentsExistError(f"employee {employee_id} is inactive; cannot attach a project")


def attach_project(
    actor: Employee, employee_id: int, name: str, completed_at
) -> tuple[list[ProjectAssignment], bool]:
    """Attaches a project by name — get-or-create the project (never
    touching description — see ProjectAttach's docstring), then link it,
    optionally setting completed_at.

    completed_at of None (whether omitted from the request or sent
    explicitly as null — the two are indistinguishable on this schema,
    deliberately: both mean "no completion date to set right now") maps
    to UNSET at the repository, so a re-attach of a project the employee
    already completed does NOT silently reopen it — that's what the
    dedicated PUT endpoint is for, which requires the field and can
    therefore tell "clear it" apart from "didn't say."

    Returns:
        tuple[list[ProjectAssignment], bool]: the employee's current
        projects, and whether a NEW employee_projects row was created —
        the controller uses the second to choose 201 vs 200.

    Raises:
        NotFoundError: no such employee (410).
        HTTPException: 403 if the caller isn't self, this employee's
            team manager, or Admin.
        DependentsExistError: the target employee is inactive (409).
    """
    target = employee_repository.get_employee(employee_id)
    _require_can_edit_projects(actor, target)
    _require_active_target(employee_id, target)

    project = project_repository.get_or_create_project(name)
    completed_at_value = completed_at if completed_at is not None else project_repository.UNSET
    created = project_repository.attach_project(employee_id, project.id, completed_at=completed_at_value)
    return project_repository.list_employee_projects(employee_id), created


def update_completion(actor: Employee, employee_id: int, project_id: int, completed_at) -> list[ProjectAssignment]:
    """Sets (or, given null, clears — reopens) the completion date for
    an assignment. Upserts: if the employee wasn't already attached to
    this project, this creates the attachment — same as attach_project,
    just addressed by project_id (already known) instead of name, and
    always passing an explicit completed_at (this endpoint's only job),
    so it never hits the "leave it alone" no-op branch attach_project
    has for an omitted value.

    Raises:
        NotFoundError: no such employee, or no such project (both 410).
        HTTPException: 403 if the caller isn't self, this employee's
            team manager, or Admin.
        DependentsExistError: the target employee is inactive (409) —
            this can create a new row, same as attach.
    """
    target = employee_repository.get_employee(employee_id)
    _require_can_edit_projects(actor, target)
    _require_active_target(employee_id, target)

    project_repository.get_project(project_id)  # raises NotFoundError if no such project
    project_repository.attach_project(employee_id, project_id, completed_at=completed_at)
    return project_repository.list_employee_projects(employee_id)


def detach_project(actor: Employee, employee_id: int, project_id: int) -> list[ProjectAssignment]:
    """Detaches a project. Clean success whether or not the employee had
    it, no is_active guard — same reasoning as skill_service.detach_skill.
    """
    target = employee_repository.get_employee(employee_id)
    _require_can_edit_projects(actor, target)
    project_repository.detach_project(employee_id, project_id)
    return project_repository.list_employee_projects(employee_id)
