"""Domain exceptions shared across repositories and services.

Not scoped under services/ because repositories raise these too (a
repository is the one that knows a row wasn't found), and every later
slice's "get by id" endpoint reuses NotFoundError.
"""


class NotFoundError(Exception):
    """Raised when a requested record does not exist."""
