"""chat_sessions / chat_messages.

Data-access tests are pure Postgres, no LLM call. The endpoint tests exercise
POST /chat, /sessions and DELETE for real -- same real-service cost tradeoff
already accepted in test_router.py.
"""
import pytest
from fastapi.testclient import TestClient

from app.auth.security import hash_password
from app.data_access import chat_history as ch
from app.data_access.users import create_user, delete_user
from app.main import app

TEST_USER = "pytest_chatuser"
OTHER_USER = "pytest_chatuser_other"
TEST_PASSWORD = "pytest-password-1234"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user_id():
    """A real users row: chat_sessions.user_id is a foreign key, so a session
    can't be created for an id nothing backs. Deleting the user cascades to its
    sessions and, from there, its messages -- one cleanup step covers all three
    tables.
    """
    ch.ensure_tables()
    delete_user(TEST_USER)
    row = create_user(TEST_USER, hash_password(TEST_PASSWORD))
    yield row["id"]
    delete_user(TEST_USER)


# --- data access ---------------------------------------------------------


def test_create_and_get_session(user_id):
    session_id = ch.create_session(user_id, "What was Apple's revenue in 2025?")
    session = ch.get_session(session_id, user_id)
    assert session is not None
    assert session["title"] == "What was Apple's revenue in 2025?"


def test_get_session_returns_none_for_a_different_owner(user_id):
    # Not a real user id -- get_session only ever filters on it, so it does not
    # need to exist to prove "some other account can't see this".
    session_id = ch.create_session(user_id, "some question")
    assert ch.get_session(session_id, user_id + 1) is None


def test_title_is_truncated_for_a_long_question():
    title = ch._title_from("a" * 100)
    assert title == "a" * ch.TITLE_MAX_LENGTH + "…"


def test_title_is_untouched_when_short():
    assert ch._title_from("  Apple revenue 2025  ") == "Apple revenue 2025"


def test_list_sessions_orders_most_recently_updated_first(user_id):
    first = ch.create_session(user_id, "first")
    ch.create_session(user_id, "second")
    ch.add_message(first, "user", "touch first again")  # bumps first's updated_at

    ids = [row["id"] for row in ch.list_sessions(user_id)]
    assert ids[0] == first


def test_add_message_and_get_messages_round_trip(user_id):
    session_id = ch.create_session(user_id, "Apple revenue 2025")
    ch.add_message(session_id, "user", "Apple revenue 2025")
    ch.add_message(
        session_id,
        "assistant",
        "416 billion",
        route="sql",
        grounded=True,
        companies=["Apple"],
        citations=[],
    )

    messages = ch.get_messages(session_id)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["route"] is None  # a user message has nothing to ground
    assert messages[1]["route"] == "sql"
    assert messages[1]["companies"] == ["Apple"]


def test_delete_session_requires_ownership(user_id):
    session_id = ch.create_session(user_id, "some question")
    assert ch.delete_session(session_id, user_id + 1) is False
    assert ch.get_session(session_id, user_id) is not None  # untouched
    assert ch.delete_session(session_id, user_id) is True
    assert ch.get_session(session_id, user_id) is None


def test_delete_session_cascades_to_its_messages(user_id):
    session_id = ch.create_session(user_id, "some question")
    ch.add_message(session_id, "user", "some question")
    ch.delete_session(session_id, user_id)
    assert ch.get_messages(session_id) == []


# --- endpoints -------------------------------------------------------------


def _token(client: TestClient, username: str) -> str:
    delete_user(username)
    client.post("/auth/register", json={"username": username, "password": TEST_PASSWORD})
    login = client.post("/auth/login", data={"username": username, "password": TEST_PASSWORD})
    return login.json()["access_token"]


def test_chat_creates_and_continues_a_session(client):
    token = _token(client, TEST_USER)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/chat", json={"question": "Apple net income 2025"}, headers=headers
    )
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    assert session_id

    # The follow-up only makes sense with the first turn's history -- proving
    # it resolves correctly proves the server, not the client, now supplies
    # that history.
    second = client.post(
        "/chat",
        json={"question": "What about Google?", "session_id": session_id},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id
    assert "google" in second.json()["answer"].lower()

    listing = client.get("/sessions", headers=headers)
    assert session_id in [s["id"] for s in listing.json()]

    messages = client.get(f"/sessions/{session_id}/messages", headers=headers)
    assert [m["role"] for m in messages.json()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]

    delete_user(TEST_USER)  # cascades: session and its messages go with it


def test_chat_rejects_an_unknown_session_id(client):
    token = _token(client, TEST_USER)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/chat",
        json={"question": "Apple net income 2025", "session_id": "not-a-real-session"},
        headers=headers,
    )
    assert response.status_code == 404

    delete_user(TEST_USER)


def test_sessions_are_scoped_to_the_owning_user(client):
    owner_token = _token(client, TEST_USER)
    other_token = _token(client, OTHER_USER)

    created = client.post(
        "/chat",
        json={"question": "Apple net income 2025"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    session_id = created.json()["session_id"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    # 404, not 403: the other user should not even learn the session exists.
    assert (
        client.get(f"/sessions/{session_id}/messages", headers=other_headers).status_code
        == 404
    )
    assert client.delete(f"/sessions/{session_id}", headers=other_headers).status_code == 404
    assert client.get("/sessions", headers=other_headers).json() == []

    # The other user's failed delete attempt must not have touched it.
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    still_there = client.get(f"/sessions/{session_id}/messages", headers=owner_headers)
    assert still_there.status_code == 200
    assert len(still_there.json()) == 2

    delete_user(TEST_USER)
    delete_user(OTHER_USER)
