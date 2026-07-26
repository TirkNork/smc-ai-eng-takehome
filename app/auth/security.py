"""Password hashing and JWT encode/decode.

Pure functions -- no database, no FastAPI. Keeping the crypto separate from the
routes means the scheme can change (longer expiry, extra claims, a different
algorithm) without touching request handling, and it is testable on its own.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings


class InvalidToken(Exception):
    """Expired, tampered with, or otherwise not a token we issued."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def username_from_token(token: str) -> str:
    """The `sub` claim, or InvalidToken. `algorithms` is an allow-list: without
    it a token could name its own algorithm, including "none"."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc

    username = payload.get("sub")
    if not username:
        raise InvalidToken("token carries no subject")
    return username
