"""Team row model."""

from dataclasses import dataclass
from datetime import datetime


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
