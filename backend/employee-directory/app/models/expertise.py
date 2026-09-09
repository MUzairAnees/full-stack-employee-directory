"""Expertise row model."""

from dataclasses import dataclass


@dataclass
class Expertise:
    """A single expertise area, assigned to an employee at creation."""

    id: int
    name: str
