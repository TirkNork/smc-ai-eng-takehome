"""Register and login.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, status

from app.auth.security import create_access_token, hash_password, verify_password
from app.data_access.users import create_user, ensure_table, get_user
from app.schemas.auth import Credentials, Token, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect username or password.",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
def register(credentials: Credentials) -> User:
    # CREATE TABLE IF NOT EXISTS -- cheap, and this is the only path that needs
    # the table to already exist, so there is no separate setup script to run.
    ensure_table()
    created = create_user(credentials.username, hash_password(credentials.password))
    if created is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken.")
    return User(**created)


@router.post("/login", response_model=Token)
def login(username: Annotated[str, Form()], password: Annotated[str, Form()]) -> Token:
    try:
        row = get_user(username)
    except Exception:
        logger.exception("could not look up user %s", username)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The service is temporarily unavailable.",
        )

    # One message and one status for both failures, so a client can't tell
    # "no such user" apart from "wrong password" from the response alone.
    if row is None or not verify_password(password, row["password_hash"]):
        raise INVALID_CREDENTIALS

    return Token(access_token=create_access_token(row["username"]))
