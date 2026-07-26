"""Auth: hashing and tokens are pure and run offline; the endpoint tests use
TestClient against the real Postgres, like the other data-access tests.

Requires JWT_SECRET in .env. The users table itself needs no setup -- the first
/auth/register call in this file creates it.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.security import (
    InvalidToken,
    create_access_token,
    hash_password,
    username_from_token,
    verify_password,
)
from app.config import settings
from app.data_access.users import delete_user, ensure_table
from app.main import app

TEST_USER = "pytest_authuser"
TEST_PASSWORD = "pytest-password-1234"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fresh_user():
    """Removed before and after, so a failed run cannot leave a user behind that
    makes the next run fail on 409. ensure_table() covers running this suite
    against a brand new database, where nothing has called /auth/register yet."""
    ensure_table()
    delete_user(TEST_USER)
    yield TEST_USER
    delete_user(TEST_USER)


# --- hashing -----------------------------------------------------------------


def test_password_round_trip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_hash_is_salted():
    # Same password, different hashes -- otherwise identical passwords would be
    # visible as identical rows in the table.
    assert hash_password("same-password") != hash_password("same-password")


# --- tokens ------------------------------------------------------------------


def test_token_round_trip():
    assert username_from_token(create_access_token("alice")) == "alice"


def test_expired_token_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    token = create_access_token("alice")
    with pytest.raises(InvalidToken):
        username_from_token(token)


def test_token_signed_with_another_secret_is_rejected():
    # The core of the scheme: holding the payload format is not enough, you need
    # the signing key.
    forged = jwt.encode(
        {"sub": "alice", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "not-our-secret",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidToken):
        username_from_token(forged)


def test_tampered_token_is_rejected():
    token = create_access_token("alice")
    with pytest.raises(InvalidToken):
        username_from_token(token[:-2] + ("aa" if not token.endswith("aa") else "bb"))


def test_token_without_subject_is_rejected():
    empty = jwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidToken):
        username_from_token(empty)


# --- endpoints ---------------------------------------------------------------


def test_chat_requires_a_token(client):
    response = client.post("/chat", json={"question": "Apple revenue 2025"})
    assert response.status_code == 401


def test_chat_rejects_a_garbage_token(client):
    response = client.post(
        "/chat",
        json={"question": "Apple revenue 2025"},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


def test_health_stays_public(client):
    # A probe must be able to tell "the stack is down" from "not signed in".
    assert client.get("/health").status_code == 200


def test_register_then_login(client, fresh_user):
    created = client.post(
        "/auth/register", json={"username": fresh_user, "password": TEST_PASSWORD}
    )
    assert created.status_code == 201
    assert created.json()["username"] == fresh_user
    assert "password_hash" not in created.json()

    login = client.post("/auth/login", data={"username": fresh_user, "password": TEST_PASSWORD})
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_register_rejects_a_duplicate_username(client, fresh_user):
    body = {"username": fresh_user, "password": TEST_PASSWORD}
    assert client.post("/auth/register", json=body).status_code == 201
    assert client.post("/auth/register", json=body).status_code == 409


def test_register_rejects_a_short_password(client, fresh_user):
    response = client.post("/auth/register", json={"username": fresh_user, "password": "short"})
    assert response.status_code == 422


def test_register_rejects_a_password_over_32_characters(client, fresh_user):
    # 33: one over the limit, so this actually tests the boundary rather than
    # just "clearly too long by any standard".
    response = client.post(
        "/auth/register", json={"username": fresh_user, "password": "a" * 33}
    )
    assert response.status_code == 422


def test_a_multibyte_password_under_the_character_limit_still_crashes_hashing(client, fresh_user):
    """Known gap, not a regression: max_length=32 counts characters, and bcrypt's
    own limit is 72 BYTES. 30 Thai characters is under our 32-character limit
    but 90 bytes, so it reaches hash_password() uncaught -- TestClient re-raises
    rather than returning a 500, which is what surfaces here. Documented rather
    than silently fixed, since the project chose the simple Field-only check
    over a byte-precise validator."""
    with pytest.raises(ValueError, match="72 bytes"):
        client.post("/auth/register", json={"username": fresh_user, "password": "ก" * 30})


def test_login_with_a_wrong_password_is_401(client, fresh_user):
    client.post("/auth/register", json={"username": fresh_user, "password": TEST_PASSWORD})
    response = client.post("/auth/login", data={"username": fresh_user, "password": "wrong-password"})
    assert response.status_code == 401


def test_unknown_and_wrong_password_are_indistinguishable(client, fresh_user):
    """Same status and same message, so neither reveals which usernames exist."""
    client.post("/auth/register", json={"username": fresh_user, "password": TEST_PASSWORD})

    wrong_password = client.post(
        "/auth/login", data={"username": fresh_user, "password": "wrong-password"}
    )
    no_such_user = client.post(
        "/auth/login", data={"username": "definitely_not_registered", "password": TEST_PASSWORD}
    )

    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json()["detail"] == no_such_user.json()["detail"]
