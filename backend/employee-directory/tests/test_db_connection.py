"""Tests that the module-level connection is reused, not reopened."""

from unittest.mock import MagicMock, patch

import psycopg

import app.repositories.db as db


def test_connection_reused_not_reopened() -> None:
    """Two calls to get_connection() in the same container must share one
    connection object. Migration itself is covered by test_work_locations.py,
    so it's skipped here to isolate what this test is actually checking.
    """
    db._CONN = None
    db._SCHEMA_READY = True

    fake_conn = MagicMock()
    fake_conn.closed = False

    try:
        with patch("app.repositories.db.connect", return_value=fake_conn) as mock_connect:
            first = db.get_connection()
            second = db.get_connection()

        assert first is second
        mock_connect.assert_called_once()
    finally:
        # Don't leak the mock connection into later tests that need the real one.
        db._CONN = None
        db._SCHEMA_READY = False


def test_migration_is_idempotent_when_run_twice_in_one_process() -> None:
    """Calling ensure_schema twice in the same process must not error and
    must not duplicate seed rows — ON CONFLICT DO NOTHING doing its job,
    not just the once-per-container flag preventing a second call.
    """
    from app.db_init import ensure_schema

    conn = db.get_connection()  # already migrated once via app startup

    ensure_schema(conn)
    ensure_schema(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM work_locations WHERE name = 'Remote'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM expertise")
        assert cur.fetchone()[0] == 4


def test_connection_survives_a_rolled_back_transaction() -> None:
    """Slice 5 introduces this codebase's first multi-statement, genuinely
    atomic writes (with conn.transaction():, in employee_repository and
    team_repository) — load-bearing to prove, not assume, that a failed
    one leaves the module-level connection usable for the NEXT request on
    the same warm container. It's tempting to assume db.py's
    reset-on-failure (see get_connection()) covers this, but it doesn't:
    that reset only fires INSIDE get_connection() itself (a failed
    connect() or ensure_schema()) — a mid-request rollback inside a
    `with conn.transaction():` block never goes through get_connection()
    again at all, so nothing there would catch a stuck connection if
    conn.transaction() didn't clean up properly on its own.

    Forces a REAL UniqueViolation, not a bare `raise` — a bare Python
    exception unwinds without the SERVER ever putting the transaction
    into the aborted state, which is where a genuinely stuck connection
    would actually come from. A real constraint violation is the only
    thing that exercises that.
    """
    conn = db.get_connection()

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM work_locations WHERE name = 'Remote'")
        existing_id = cur.fetchone()[0]

    raised = False
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("INSERT INTO work_locations (name) VALUES ('Remote')")
    except psycopg.errors.UniqueViolation:
        raised = True
    assert raised, "expected a UniqueViolation from the duplicate 'Remote' insert"

    # The SAME connection object — not a fresh db.get_connection() call —
    # must still work for an ordinary statement immediately afterward.
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM work_locations WHERE id = %s", (existing_id,))
        assert cur.fetchone()[0] == existing_id


def test_connection_recovers_after_being_closed() -> None:
    """If the pooled connection gets closed from under us — which does
    happen to idle Lambda containers when the database drops it — the
    next call must reconnect rather than error. That branch has existed
    in get_connection() since slice 1 but was never actually exercised by
    a test until now.
    """
    db.get_connection()  # ensure a real connection exists first
    db._CONN.close()
    assert db._CONN.closed

    conn = db.get_connection()

    assert conn is not None
    assert not conn.closed
