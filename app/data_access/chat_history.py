"""chat_sessions / chat_messages -- same parameterized raw-psycopg style as
financial_data.py and users.py.

session_id is a plain `text` UUID generated in Python (uuid4), not a Postgres
`uuid` column -- one fewer type to think about, and there is nothing here that
needs the database to validate or generate it.

Every read/write here takes `user_id` and filters on it: a session belongs to
exactly the user who started it, and a caller must not be able to reach
another user's conversation by guessing a session_id.
"""
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.data_access.db import connection, run_ddl

CREATE_TABLES = """
create table if not exists chat_sessions (
    id         text primary key,
    user_id    int not null references users(id) on delete cascade,
    title      text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists chat_messages (
    id             serial primary key,
    session_id     text not null references chat_sessions(id) on delete cascade,
    role           text not null check (role in ('user', 'assistant')),
    content        text not null,
    route          text,
    grounded       boolean,
    missing_reason text,
    companies      jsonb,
    citations      jsonb,
    created_at     timestamptz not null default now()
)
"""

# Shown in the session list -- kept short so it reads like a chat title, not
# the full question.
TITLE_MAX_LENGTH = 60


_tables_ready = False


def ensure_tables() -> None:
    """Creates the tables on the first successful call and does nothing on
    every call after it.

    main.lifespan calls this at startup, which is where it belongs. But
    startup deliberately survives an unreachable Postgres, so the result is
    remembered rather than assumed: if the DDL did not get to run at boot, the
    next request retries it, and once it has succeeded no request pays for it
    again. The flag is per-process, so `run_ddl` still has to tolerate two
    workers racing on the first one.
    """
    global _tables_ready
    if _tables_ready:
        return
    run_ddl(CREATE_TABLES)
    _tables_ready = True


def _title_from(question: str) -> str:
    question = question.strip()
    if len(question) <= TITLE_MAX_LENGTH:
        return question
    return question[:TITLE_MAX_LENGTH].rstrip() + "…"


def create_session(user_id: int, first_question: str) -> str:
    """A new session id (Python-generated uuid4, stringified)."""
    session_id = str(uuid.uuid4())
    with connection() as conn:
        conn.execute(
            "insert into chat_sessions (id, user_id, title) values (%s, %s, %s)",
            (session_id, user_id, _title_from(first_question)),
        )
    return session_id


def get_session(session_id: str, user_id: int) -> dict | None:
    """None when the session does not exist OR belongs to someone else -- the
    caller treats both the same way (404), so they are not distinguished here."""
    with connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id, title, created_at, updated_at from chat_sessions"
                " where id = %s and user_id = %s",
                (session_id, user_id),
            )
            return cur.fetchone()


def list_sessions(user_id: int) -> list[dict]:
    """Most recently active first."""
    with connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id, title, created_at, updated_at from chat_sessions"
                " where user_id = %s order by updated_at desc",
                (user_id,),
            )
            return cur.fetchall()


def delete_session(session_id: str, user_id: int) -> bool:
    """False when there was no such session owned by this user. Messages go
    with it via ON DELETE CASCADE -- nothing else references a session."""
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from chat_sessions where id = %s and user_id = %s",
                (session_id, user_id),
            )
            return cur.rowcount > 0


def get_messages(session_id: str) -> list[dict]:
    """Oldest first -- the order the conversation actually happened in.

    Ownership is not re-checked here: every caller already resolved the
    session through get_session(), which is where the (session_id, user_id)
    check lives.
    """
    with connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select role, content, route, grounded, missing_reason,"
                " companies, citations, created_at from chat_messages"
                " where session_id = %s order by id",
                (session_id,),
            )
            return cur.fetchall()


def add_message(
    session_id: str,
    role: str,
    content: str,
    *,
    route: str | None = None,
    grounded: bool | None = None,
    missing_reason: str | None = None,
    companies: list[str] | None = None,
    citations: list[dict] | None = None,
) -> None:
    """route/grounded/... are only ever set for role="assistant" -- a user
    message has nothing to ground, so its columns stay null."""
    with connection() as conn:
        conn.execute(
            "insert into chat_messages (session_id, role, content, route,"
            " grounded, missing_reason, companies, citations)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                session_id,
                role,
                content,
                route,
                grounded,
                missing_reason,
                Jsonb(companies) if companies is not None else None,
                Jsonb(citations) if citations is not None else None,
            ),
        )
        conn.execute(
            "update chat_sessions set updated_at = now() where id = %s", (session_id,)
        )
