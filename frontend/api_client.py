"""HTTP client for the FastAPI backend. The only place that knows its URL.

The token is a parameter on every call, never module state: this module is
imported once per process but serves every browser session, so a token held here
would be shared between users.
"""
import os

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class BackendError(Exception):
    """Backend unreachable or returned an error -- distinct from the agent
    answering "I don't have that data", which is a successful response."""


class AuthError(Exception):
    """Credentials rejected, or the token is no longer good. Kept apart from
    BackendError so the UI can send the user back to the form rather than
    showing a service failure."""


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _unreachable(exc: httpx.RequestError) -> BackendError:
    return BackendError(f"Cannot reach the API at {BACKEND_URL} ({type(exc).__name__}).")


def register(username: str, password: str) -> None:
    try:
        response = httpx.post(
            f"{BACKEND_URL}/auth/register",
            json={"username": username, "password": password},
            timeout=TIMEOUT,
        )
    except httpx.RequestError as exc:
        raise _unreachable(exc) from exc

    if response.status_code == 409:
        raise AuthError("That username is taken.")
    if response.status_code == 422:
        # The API's own validation message, so the rules live in one place.
        raise AuthError(_first_validation_error(response))
    if response.status_code >= 400:
        raise BackendError(f"API returned {response.status_code}.")


def login(username: str, password: str) -> str:
    """The access token. Sent form-encoded (httpx `data=`), matching the two
    plain Form() fields /auth/login expects -- not JSON."""
    try:
        response = httpx.post(
            f"{BACKEND_URL}/auth/login",
            data={"username": username, "password": password},
            timeout=TIMEOUT,
        )
    except httpx.RequestError as exc:
        raise _unreachable(exc) from exc

    if response.status_code == 401:
        raise AuthError("Incorrect username or password.")
    if response.status_code >= 400:
        raise BackendError(f"API returned {response.status_code}.")

    return response.json()["access_token"]


def ask(question: str, history: list[dict] | None = None, token: str = "") -> dict:
    try:
        response = httpx.post(
            f"{BACKEND_URL}/chat",
            json={"question": question, "history": history or []},
            headers=_bearer(token),
            timeout=TIMEOUT,
        )
    except httpx.RequestError as exc:
        raise _unreachable(exc) from exc

    if response.status_code == 401:
        # Reachable mid-conversation: the token expired since sign-in.
        raise AuthError("Your session expired. Please sign in again.")
    if response.status_code == 503:
        raise BackendError("The assistant is temporarily unavailable. Please try again.")
    if response.status_code >= 400:
        raise BackendError(f"API returned {response.status_code}.")

    return response.json()


def _first_validation_error(response: httpx.Response) -> str:
    try:
        return response.json()["detail"][0]["msg"].removeprefix("Value error, ")
    except Exception:
        return "Those details are not valid."


def health() -> dict | None:
    """None when the backend cannot be reached at all."""
    try:
        return httpx.get(f"{BACKEND_URL}/health", timeout=httpx.Timeout(5.0)).json()
    except httpx.RequestError:
        return None
