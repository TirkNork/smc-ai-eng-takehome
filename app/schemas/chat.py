from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


class Citation(BaseModel):
    """Where a 10-K excerpt used in the answer came from."""

    company: str
    page: int


class ChatResponse(BaseModel):
    answer: str
    session_id: str

    # Grounding metadata -- exposed so a client can show *why* an answer is
    # trustworthy, and surface a partial-coverage warning rather than letting
    # the gap hide inside prose.
    route: str
    grounded: bool
    missing_reason: str | None = None
    companies: list[str] = []
    citations: list[Citation] = []


class SessionSummary(BaseModel):
    """One row in the session list -- no message content, just enough to
    render and pick a conversation."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    """One stored turn. The grounding fields are None for role="user"."""

    role: str
    content: str
    route: str | None = None
    grounded: bool | None = None
    missing_reason: str | None = None
    companies: list[str] = []
    citations: list[Citation] = []
    created_at: datetime
