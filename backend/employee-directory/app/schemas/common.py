"""Shared, reusable schema types.

Not scoped to any one resource: department names today, employee
first_name/last_name/etc. from slice 4 onward reuse the same type rather
than each reinventing its own name validation.
"""

from typing import Annotated

from pydantic import BeforeValidator, StringConstraints

NonEmptyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
"""A name field: leading/trailing whitespace stripped BEFORE the length
check, then rejected if empty (or, after stripping, effectively empty)
or absurdly long.

The strip matters more than the reject: without it, "Sales" and
" Sales " are distinct strings as far as a UNIQUE constraint is
concerned, and you get two records nobody can tell apart in a UI — worse
than a blank name, because it isn't visibly wrong.
"""


def _strip_to_none(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    return stripped or None


OptionalTrimmedText = Annotated[str | None, BeforeValidator(_strip_to_none)]
"""An optional text field (e.g. phone) where a value IS allowed to be
absent — unlike NonEmptyName, empty isn't rejected. But "  " and "" are
still not a real value: stripped, and if that leaves nothing, stored as
NULL, not as an empty string. The same invisible-value bug NonEmptyName
fixes for names, in a column that can properly express "not set" instead
of forcing a value to exist at all.
"""
