"""Liveness plus a dependency check, so a reviewer can confirm the local
stack is wired up before trying a question."""
from fastapi import APIRouter

from app.data_access.sql import list_known_companies
from app.data_access.vector import get_index_stats

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    checks: dict[str, str] = {}

    try:
        checks["postgres"] = f"ok ({len(list_known_companies())} companies)"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        checks["pinecone"] = f"ok ({get_index_stats()} vectors)"
    except Exception as exc:
        checks["pinecone"] = f"error: {type(exc).__name__}"

    ok = all(v.startswith("ok") for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}
