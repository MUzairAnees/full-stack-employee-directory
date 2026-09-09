"""Cold-start schema migration and seeding.

This project has no migration framework: the app applies schema.sql then
seed.sql to itself, idempotently, on the first database call in a given
Lambda container (see db.py for the once-per-container guard). This is a
deliberate workshop-scope choice — see README.md.

A module-level flag only protects a single warm container across repeat
invocations; it does nothing for two containers cold-starting at the same
moment, and Postgres does not guarantee CREATE TABLE IF NOT EXISTS is race
free under true concurrency (two sessions can both pass the "doesn't
exist" check before either commits). A Postgres advisory lock closes that
gap: concurrent containers serialize on it, so only one ever actually runs
the DDL/seed while the others wait, then find it already done.
"""

import logging
from pathlib import Path

from psycopg import Connection

logger = logging.getLogger(__name__)

_SERVICE_ROOT = Path(__file__).resolve().parent.parent
_ADVISORY_LOCK_KEY = 727271  # arbitrary, fixed for the life of this schema


def ensure_schema(conn: Connection) -> None:
    """Applies schema.sql then seed.sql, serialized against other
    containers via a session-scoped Postgres advisory lock.

    Args:
        conn: An open, autocommit connection.
    """
    schema_sql = (_SERVICE_ROOT / "schema.sql").read_text()
    seed_sql = (_SERVICE_ROOT / "seed.sql").read_text()

    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        logger.info("Migration: acquired advisory lock %s, applying schema.sql and seed.sql", _ADVISORY_LOCK_KEY)
        try:
            cur.execute(schema_sql)
            cur.execute(seed_sql)
            logger.info("Migration: schema.sql and seed.sql applied for this container")
        finally:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
