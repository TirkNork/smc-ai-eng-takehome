"""users table access -- same parameterized raw-psycopg style as financial_data.py.

Returns plain dicts and never raises on "not found" / "already taken": the
caller decides what those mean, so this layer stays free of HTTP concerns.
"""
from psycopg.rows import dict_row

from app.data_access.db import connection, run_ddl

# No migration tool for one table -- main.lifespan calls ensure_table() at
# startup, so there is nothing to run before the app can create its first user.
CREATE_TABLE = """
create table if not exists users (
    id            serial primary key,
    username      text not null unique,
    password_hash text not null,
    created_at    timestamptz not null default now()
)
"""


_table_ready = False


def ensure_table() -> None:
    """Creates the table on the first successful call and does nothing on
    every call after it -- see chat_history.ensure_tables for why the result
    is remembered rather than re-run."""
    global _table_ready
    if _table_ready:
        return
    run_ddl(CREATE_TABLE)
    _table_ready = True


def get_user(username: str) -> dict | None:
    with connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id, username, password_hash from users where username = %s",
                (username,),
            )
            return cur.fetchone()


def create_user(username: str, password_hash: str) -> dict | None:
    """None when the username is already taken."""
    with connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "insert into users (username, password_hash) values (%s, %s)"
                " on conflict (username) do nothing returning id, username",
                (username, password_hash),
            )
            return cur.fetchone()


def delete_user(username: str) -> bool:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from users where username = %s", (username,))
            return cur.rowcount > 0
