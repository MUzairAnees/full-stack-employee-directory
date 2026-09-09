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
    """Raised when a delete is blocked because active records still
    depend on the one being deleted.
    """
