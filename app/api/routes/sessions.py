"""List, read, and delete a signed-in user's stored conversations."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.data_access.chat_history import delete_session, get_messages, get_session, list_sessions
from app.schemas.auth import User
from app.schemas.chat import Message, SessionSummary

router = APIRouter(prefix="/sessions", tags=["chat"])


@router.get("", response_model=list[SessionSummary])
def sessions(user: Annotated[User, Depends(get_current_user)]) -> list[SessionSummary]:
    return [SessionSummary(**row) for row in list_sessions(user.id)]


@router.get("/{session_id}/messages", response_model=list[Message])
def session_messages(
    session_id: str, user: Annotated[User, Depends(get_current_user)]
) -> list[Message]:
    # Ownership check lives here -- get_messages() itself trusts session_id
    # once this has passed.
    if get_session(session_id, user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.")

    return [
        Message(**{**row, "companies": row["companies"] or [], "citations": row["citations"] or []})
        for row in get_messages(session_id)
    ]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_session(session_id: str, user: Annotated[User, Depends(get_current_user)]) -> None:
    if not delete_session(session_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.")
