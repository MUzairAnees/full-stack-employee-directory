"""Team row models."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class Team:
    """A team. manager_id is never NULL — schema.sql's teams table
    declares it NOT NULL — because a team without a manager isn't a
    partial team, it's ended (see team_repository.soft_delete_team).
    """

    id: int
    name: str
    department_id: int
    manager_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class Achievement:
    """One completed project, attributed to whoever is CURRENTLY on the
    team (see team_repository.get_team_achievements) — a row from
    GET /teams/{id}/achievements, not a stored entity of its own.
    """

    employee_id: int
    employee_first_name: str
    employee_last_name: str
    project_id: int
    project_name: str
    completed_at: date
