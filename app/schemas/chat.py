from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """One earlier message in the conversation."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = []


class Citation(BaseModel):
    """Where a 10-K excerpt used in the answer came from."""

    company: str
    page: int


class ChatResponse(BaseModel):
    answer: str

    # Grounding metadata -- exposed so a client can show *why* an answer is
    # trustworthy, and surface a partial-coverage warning rather than letting
    # the gap hide inside prose.
    route: str
    grounded: bool
    missing_reason: str | None = None
    companies: list[str] = []
    citations: list[Citation] = []
