"""PostgreSQL connection management.

Reuses a single module-level connection across warm Lambda invocations,
the same pattern as backend/_examples/python-service/postgres_service.py:
reconnect if missing or closed, reset to None on failure so the next call
retries. IS_LOCAL is used in exactly one place — here, to pick sslmode —
and nowhere else in this codebase branches on environment.
"""

import os

from psycopg import Connection, connect

from app.db_init import ensure_schema

_CONN: Connection | None = None
_SCHEMA_READY = False


def _build_conninfo() -> str:
    """Builds a libpq connection string from the POSTGRES_* env vars
    Terraform injects (see infra/locals.tf). Aurora requires SSL; local
    Postgres does not.

    connect_timeout is 30s, not the more typical 10-15s: Aurora Serverless
    v2 here has min_capacity=0 (infra/rds.tf), so it scales to zero after
    a few idle minutes and the next connection has to wait for it to
    resume from a cold ACU. Confirmed empirically — the first connection
    after a period of no traffic timed out at 15s, a retry moments later
    succeeded in ~1.4s. Local Postgres is never scaled down, so this only
    ever matters against Aurora.
    """
    sslmode = "disable" if os.getenv("IS_LOCAL", "false") == "true" else "require"
    return (
        f"host={os.environ['POSTGRES_HOST']} "
        f"port={os.environ['POSTGRES_PORT']} "
        f"dbname={os.environ['POSTGRES_NAME']} "
        f"user={os.environ['POSTGRES_USER']} "
        f"password={os.environ['POSTGRES_PASS']} "
        f"sslmode={sslmode} "
        f"connect_timeout=30"
    )


def get_connection() -> Connection:
    """Returns the shared connection, reconnecting if needed, and ensures
    the schema/seed have been applied once for this container.

    Raises:
        Exception: If connecting or migrating fails; resets the pooled
            connection so the next call retries from scratch.
    """
    global _CONN, _SCHEMA_READY
    try:
        if _CONN is None or _CONN.closed:
            _CONN = connect(_build_conninfo(), autocommit=True)
            _SCHEMA_READY = False  # a fresh connection means a fresh container

        if not _SCHEMA_READY:
            ensure_schema(_CONN)
            _SCHEMA_READY = True

        return _CONN
    except Exception:
        _CONN = None
        _SCHEMA_READY = False
        raise
