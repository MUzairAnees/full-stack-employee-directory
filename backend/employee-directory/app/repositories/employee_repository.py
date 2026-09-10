"""Data access for employees (auth-relevant queries only, this slice)."""

from psycopg.rows import class_row

from app.models.employee import Employee
from app.repositories.db import get_connection

_COLUMNS = "id, first_name, last_name, email, password_hash, role, is_active"


def get_employee_by_email(email: str) -> Employee | None:
    """Returns the employee with this email, or None if none exists.

    Unlike work_location_repository.get_work_location, this returns None
    rather than raising NotFoundError: login needs to tell "no such
    email" apart from other conditions itself, on the way to giving an
    identical, generic 401 regardless of which one it was (see
    auth_service.authenticate).

    Matches on LOWER(email), not email — deliberately, and matching
    schema.sql's idx_employees_email_lower index (which this query now
    actually uses, not just benefits from indirectly). auth_service
    already lowercases the input before calling this, so today the two
    forms behave identically; the difference only matters for a row
    that's ever stored with mixed case. With a plain `email = %s`, that
    row would be UNREACHABLE — permanently unable to log in, no error
    explaining why — rather than just inconsistent. LOWER(email) finds
    it regardless of how it was stored, which is the whole point of
    normalizing being cheap insurance rather than a strict guarantee.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Employee)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM employees WHERE LOWER(email) = %s", (email,))
        return cur.fetchone()


def get_employee_by_id(employee_id: int) -> Employee | None:
    """Returns the employee with this id, or None if none exists.

    Used by the current_user dependency to re-read the employee (and in
    particular is_active) from the database on every authenticated
    request, rather than trusting the JWT payload.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Employee)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM employees WHERE id = %s", (employee_id,))
        return cur.fetchone()
