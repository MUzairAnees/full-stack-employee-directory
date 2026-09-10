"""Domain exceptions shared across repositories and services.

Not scoped under services/ because repositories raise these too (a
repository is the one that knows a row wasn't found), and every later
slice's "get by id" endpoint reuses NotFoundError.
"""


class NotFoundError(Exception):
    """Raised when a requested record does not exist."""


class DuplicateError(Exception):
    """Raised when a create/update would violate a uniqueness
    constraint — most often a name colliding with a soft-deleted row,
    since soft delete keeps the name (the unique constraint doesn't know
    or care that the row is inactive).
    """


class DependentsExistError(Exception):
    """Raised when a delete/deactivate is blocked — either because active
    records still depend on the one being deactivated (e.g. direct
    reports, or a department's active employees), or because doing so
    would violate a system invariant (the CEO can never be deactivated;
    at least one active Admin must always remain).
    """


class InvalidReferenceError(Exception):
    """Raised when a foreign key reference doesn't exist. Names the
    specific field — employees have four FK columns
    (work_location_id/team_id/manager_id/expertise_id), and "invalid
    reference" alone doesn't tell the caller which one they got wrong.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)
