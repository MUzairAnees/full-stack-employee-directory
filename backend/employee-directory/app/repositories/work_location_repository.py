"""Data access for work_locations."""

from psycopg.rows import class_row

from app.exceptions import NotFoundError
from app.models.work_location import WorkLocation
from app.repositories.db import get_connection

_COLUMNS = "id, name, address_line_1, city, state, zip, created_at, updated_at"


def list_work_locations() -> list[WorkLocation]:
    """Returns every work location, ordered by name.

    Returns:
        list[WorkLocation]: All rows in work_locations.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(WorkLocation)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM work_locations ORDER BY name")
        return cur.fetchall()


def get_work_location(location_id: int) -> WorkLocation:
    """Returns a single work location by id.

    Args:
        location_id: The work location's id.

    Returns:
        WorkLocation: The matching row.

    Raises:
        NotFoundError: If no work location has that id.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(WorkLocation)) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM work_locations WHERE id = %s", (location_id,))
        row = cur.fetchone()
        if row is None:
            raise NotFoundError(f"work location {location_id} not found")
        return row
