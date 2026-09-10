"""Skill row model."""

from dataclasses import dataclass


@dataclass
class Skill:
    """A skill in the shared lookup list. Global, not per-employee — the
    per-employee relationship is the employee_skills join table (see
    skill_repository), not a field here.
    """

    id: int
    name: str
