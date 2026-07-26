import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_graph
from app.data_access.companies import COMPANY_BY_VECTOR_TITLE
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
def chat(payload: ChatRequest, graph=Depends(get_graph)) -> ChatResponse:
    try:
        state = graph.invoke({"question": payload.question})
    except Exception:
        # Data-source failures are already handled inside the graph and come
        # back as a normal grounded=False answer. Reaching here means the LLM
        # provider itself failed, so surface it as a service error rather than
        # letting a stack trace escape as a 500.
        logger.exception("agent failed for question: %s", payload.question)
        raise HTTPException(status_code=503, detail="The assistant is temporarily unavailable.")

    return ChatResponse(
        answer=state["answer"],
        route=state["route"],
        grounded=state["grounded"],
        missing_reason=state.get("missing_reason"),
        companies=state.get("companies") or [],
        citations=_citations(state.get("vector_results") or []),
    )
