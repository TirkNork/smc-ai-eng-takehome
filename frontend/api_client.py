"""HTTP client for the FastAPI backend.

The only place that knows the backend URL. When auth lands, the bearer token
is attached here -- callers keep calling ask() unchanged.
"""
import os

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class BackendError(Exception):
    """Backend unreachable or returned an error -- distinct from the agent
    answering "I don't have that data", which is a successful response."""


def ask(question: str, history: list[dict] | None = None) -> dict:
    try:
        response = httpx.post(
            f"{BACKEND_URL}/chat",
            json={"question": question, "history": history or []},
            timeout=TIMEOUT,
        )
    except httpx.RequestError as exc:
        raise BackendError(f"Cannot reach the API at {BACKEND_URL} ({type(exc).__name__}).") from exc

    if response.status_code == 503:
        raise BackendError("The assistant is temporarily unavailable. Please try again.")
    if response.status_code >= 400:
        raise BackendError(f"API returned {response.status_code}.")

    return response.json()


def health() -> dict | None:
    """None when the backend cannot be reached at all."""
    try:
        return httpx.get(f"{BACKEND_URL}/health", timeout=httpx.Timeout(5.0)).json()
    except httpx.RequestError:
        return None
