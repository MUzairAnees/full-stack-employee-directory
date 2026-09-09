"""Data access for expertise."""

from psycopg.rows import class_row

from app.models.expertise import Expertise
from app.repositories.db import get_connection


def list_expertise() -> list[Expertise]:
    """Returns every expertise value, ordered by name.

    Returns:
        list[Expertise]: All rows in expertise.
    """
    conn = get_connection()
    with conn.cursor(row_factory=class_row(Expertise)) as cur:
        cur.execute("SELECT id, name FROM expertise ORDER BY name")
        return cur.fetchall()
