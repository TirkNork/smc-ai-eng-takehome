"""FastAPI app.

Normal use -- the whole stack in Docker:
    docker compose up -d

Local dev with auto-reload, against the databases in Docker. Stop the API
container first (`docker compose stop api`), otherwise both bind port 8000
and which one answers a request is ambiguous:
    uv run uvicorn app.main:app --reload

Either way: http://localhost:8000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.graph import build_graph
from app.api.routes import auth, chat, health, sessions
from app.config import settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.jwt_secret:
        raise RuntimeError(
            "JWT_SECRET is not set. Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )

    # Compiled once rather than per request. build_graph() also enables
    # LangSmith tracing if configured. It performs no I/O, so the app still
    # starts when Postgres or Pinecone are down -- those surface per request
    # and in /health instead of blocking startup.
    app.state.graph = build_graph()
    yield


app = FastAPI(
    title="Financial Q&A API",
    description="Answers questions about US public companies, grounded in a "
    "financial database and 10-K filings. Refuses when the data is not there.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(sessions.router)
