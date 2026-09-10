"""Project row models."""

from dataclasses import dataclass
from datetime import date


@dataclass
class Project:
    """A project in the shared lookup list — id, name, description.
    Global, not per-employee. No is_active: projects have no lifecycle
    of their own in this app (see README) — state lives on the
    assignment (ProjectAssignment.completed_at), not the project.
    """

    id: int
    name: str
    description: str | None


@dataclass
class ProjectAssignment:
    """A project as attached to one employee — the project's own fields
    plus completed_at, which belongs to the employee_projects join row,
    not the project itself. Distinct from Project: the same project
    joins as a different ProjectAssignment for every employee it's
    attached to, each with its own completed_at.
    """

    id: int
    name: str
    description: str | None
    completed_at: date | None
