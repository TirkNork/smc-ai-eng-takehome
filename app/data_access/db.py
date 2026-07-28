"""One process-wide Postgres connection pool, shared by every module here.

Each function in this package used to open its own `psycopg.connect()`, which
meant a fresh TCP connect and auth handshake per statement. A single /chat turn
does eight of them -- user lookup, ensure_tables, session lookup, message
history, the classifier's company list, the financial query, and two message
inserts -- so the handshakes cost more than the queries do.

The pool keeps a few connections open and hands one out per `connection()`
block instead. Call sites are otherwise unchanged: the context manager commits
on clean exit and rolls back on an exception, exactly as `with
psycopg.connect(...)` did.
"""
import threading

from psycopg import errors
from psycopg_pool import ConnectionPool

from app.config import settings

# Built on first use rather than at import, so importing this module performs
# no I/O and needs no reachable database -- which is what lets the test suite
# and the offline scripts import it freely.
_pool: ConnectionPool | None = None
_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(
                settings.database_url,
                min_size=settings.db_pool_min_size,
                max_size=settings.db_pool_max_size,
                timeout=settings.db_pool_timeout,
                kwargs={"connect_timeout": settings.db_connect_timeout},
                # Verify a connection is alive before handing it out. Costs a
                # round-trip, but the handshake it replaces cost far more --
                # and without it the first request after a Postgres restart
                # fails on a stale socket, which connecting fresh every time
                # never did.
                check=ConnectionPool.check_connection,
                open=False,
            )
            # Returns immediately; connections are established in the
            # background, so a database that is down does not block here.
            _pool.open()
        return _pool


def open_pool() -> None:
    """Build and start the pool. Idempotent, non-blocking, and safe to call
    when Postgres is unreachable."""
    _get_pool()


def close_pool() -> None:
    """Release every pooled connection.

    A psycopg_pool pool cannot be reopened once closed, so the reference is
    dropped as well and the next `connection()` builds a fresh one. That keeps
    repeated app startups in one process working -- notably TestClient, which
    runs the lifespan (and therefore this) once per test.
    """
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def connection():
    """A pooled connection, as a context manager.

    Commits on clean exit, rolls back on an exception. Blocks at most
    `db_pool_timeout` seconds waiting for a free connection, then raises
    PoolTimeout -- callers already treat any exception here as "could not
    reach the database".
    """
    return _get_pool().connection()


def run_ddl(sql: str) -> None:
    """Run `create table if not exists` DDL, tolerating the one race it has.

    IF NOT EXISTS is not atomic in Postgres: two connections creating the same
    table at the same moment can leave one of them with a duplicate-key error
    on an internal catalog instead of a clean no-op. Both callers meant "make
    sure this exists", and after either one it does, so that specific failure
    is not an error here. Anything else -- including the database being
    unreachable -- still propagates.
    """
    try:
        with connection() as conn:
            conn.execute(sql)
    except (errors.UniqueViolation, errors.DuplicateTable, errors.DuplicateObject):
        pass
