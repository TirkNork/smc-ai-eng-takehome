import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_graph
from app.data_access.chat_history import add_message, create_session, ensure_tables, get_messages, get_session
from app.data_access.companies import COMPANY_BY_VECTOR_TITLE
from app.schemas.auth import User
from app.schemas.chat import ChatRequest, ChatResponse, Citation

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _citations(vector_results: list[dict]) -> list[Citation]:
    """One entry per distinct (company, page), preserving retrieval order."""
    seen: set[tuple[str, int]] = set()
    out: list[Citation] = []
    for chunk in vector_results:
        company = COMPANY_BY_VECTOR_TITLE.get(chunk["title"], chunk["title"])
        key = (company, chunk["page"])
        if key not in seen:
            seen.add(key)
            out.append(Citation(company=company, page=chunk["page"]))
    return out


# Sync def on purpose: the graph does blocking DB, Pinecone and OpenAI calls.
# FastAPI runs a sync endpoint in a threadpool, so those never block the event
# loop -- declaring it `async def` would.
@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    graph=Depends(get_graph),
) -> ChatResponse:
    # CREATE TABLE IF NOT EXISTS x2 -- cheap, same lazy-setup pattern as
    # /auth/register's ensure_table(). No separate setup script to run.
    ensure_tables()

    session_id = None
    history: list[dict] = []
    if payload.session_id is not None:
        session = get_session(payload.session_id, user.id)
        if session is None:
            raise HTTPException(status_code=404, detail="No such session.")
        session_id = session["id"]
        # Only role/content reach the graph -- the stored grounding metadata
        # (route, citations, ...) is for the UI, not something the LLM
        # message list understands.
        history = [{"role": m["role"], "content": m["content"]} for m in get_messages(session_id)]

    try:
        state = graph.invoke({"question": payload.question, "history": history})
    except Exception:
        # Data-source failures are already handled inside the graph and come
        # back as a normal grounded=False answer. Reaching here means the LLM
        # provider itself failed, so surface it as a service error rather than
        # letting a stack trace escape as a 500. Nothing is persisted below,
        # so a failed turn leaves no trace to retry against.
        logger.exception("agent failed for question: %s", payload.question)
        raise HTTPException(status_code=503, detail="The assistant is temporarily unavailable.")

    citations = _citations(state.get("vector_results") or [])
    companies = state.get("companies") or []

    # The session row itself is only created once a turn actually succeeds --
    # a failed first message must not leave an empty, title-only session behind.
    if session_id is None:
        session_id = create_session(user.id, payload.question)

    add_message(session_id, "user", payload.question)
    add_message(
        session_id,
        "assistant",
        state["answer"],
        route=state["route"],
        grounded=state["grounded"],
        missing_reason=state.get("missing_reason"),
        companies=companies,
        citations=[c.model_dump() for c in citations],
    )

    return ChatResponse(
        answer=state["answer"],
        session_id=session_id,
        route=state["route"],
        grounded=state["grounded"],
        missing_reason=state.get("missing_reason"),
        companies=companies,
        citations=citations,
    )
