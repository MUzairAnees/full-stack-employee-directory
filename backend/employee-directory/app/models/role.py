"""Employee role values."""

from enum import StrEnum


class Role(StrEnum):
    """The four roles. Values must match seed.sql's casing exactly —
    employees.role is a plain TEXT column, compared against these as
    strings (StrEnum members equal their string value directly).
    """

    CEO = "CEO"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"
