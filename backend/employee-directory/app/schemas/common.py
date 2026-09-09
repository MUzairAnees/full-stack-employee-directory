"""Shared, reusable schema types.

Not scoped to any one resource: department names today, employee
first_name/last_name/etc. from slice 4 onward reuse the same type rather
than each reinventing its own name validation.
"""

from typing import Annotated

from pydantic import StringConstraints

NonEmptyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
"""A name field: leading/trailing whitespace stripped BEFORE the length
check, then rejected if empty (or, after stripping, effectively empty)
or absurdly long.

The strip matters more than the reject: without it, "Sales" and
" Sales " are distinct strings as far as a UNIQUE constraint is
concerned, and you get two records nobody can tell apart in a UI — worse
than a blank name, because it isn't visibly wrong.
"""
