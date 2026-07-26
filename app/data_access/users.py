"""users table access -- same parameterized raw-psycopg style as sql.py.

Returns plain dicts and never raises on "not found" / "already taken": the
caller decides what those mean, so this layer stays free of HTTP concerns.
"""
import psycopg
from psycopg.rows import dict_row

from app.config import settings

# No migration tool for one table -- POST /auth/register calls ensure_table()
# itself, so there is nothing to run before the app can create its first user.
CREATE_TABLE = """
create table if not exists users (
    id            serial primary key,
    username      text not null unique,
    password_hash text not null,
    created_at    timestamptz not null default now()
)
"""


def ensure_table() -> None:
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(CREATE_TABLE)


def get_user(username: str) -> dict | None:
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id, username, password_hash from users where username = %s",
                (username,),
            )
            return cur.fetchone()


def create_user(username: str, password_hash: str) -> dict | None:
    """None when the username is already taken."""
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "insert into users (username, password_hash) values (%s, %s)"
                " on conflict (username) do nothing returning id, username",
                (username, password_hash),
            )
            return cur.fetchone()


def delete_user(username: str) -> bool:
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("delete from users where username = %s", (username,))
            return cur.rowcount > 0
