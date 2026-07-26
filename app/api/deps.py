"""Shared FastAPI dependencies."""
import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import InvalidToken, username_from_token
from app.data_access.users import get_user
from app.schemas.auth import User

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

# WWW-Authenticate is what makes this a spec-correct 401 rather than a bare one.
UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_graph(request: Request):
    """The compiled LangGraph, built once at startup (see main.lifespan)."""
    return request.app.state.graph


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    """Resolve the bearer token to a user, or 401.

    The row is re-read every request rather than trusted from the token's own
    claims.
    """
    if creds is None:
        raise UNAUTHENTICATED

    try:
        username = username_from_token(creds.credentials)
    except InvalidToken:
        raise UNAUTHENTICATED

    try:
        row = get_user(username)
    except Exception:
        # The token may be perfectly valid and the database simply down. That is
        # a 503, not a 401 -- telling users their credentials are invalid would
        # be a false statement about their account.
        logger.exception("could not load user %s", username)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The service is temporarily unavailable.",
        )

    if row is None:
        # Signed by us, but the account no longer exists.
        raise UNAUTHENTICATED

    return User(id=row["id"], username=row["username"])
