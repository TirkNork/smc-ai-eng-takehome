"""Query-time embedding + Pinecone search, filtered to one company's 10-K.

Returns [] immediately for a company with no filing in the vector store
(see companies.VECTOR_COVERAGE) rather than spending an embedding call on a
search that can't return anything -- callers must treat [] as "data not
available", not silently proceed.
"""
from functools import lru_cache
from urllib.parse import urlparse

from openai import OpenAI
from pinecone import Pinecone

from app.config import settings
from app.data_access.companies import VECTOR_COVERAGE, VECTOR_TITLE_BY_COMPANY

_openai_client = OpenAI(api_key=settings.openai_api_key)
_pinecone_client = Pinecone(api_key=settings.pinecone_api_key, host=settings.pinecone_host)
_index = None


def _resolve_index_host(advertised: str) -> str:
    """Turn the host describe_index reports into one we can actually reach.

    pinecone-local reports `https://<PINECONE_HOST env>:<per-index port>`, but
    serves plain HTTP -- connecting as advertised fails the TLS handshake.
    It also always reports the host *it* was configured with, which is wrong
    for whoever is calling: from the host machine that is `localhost`, but
    from another container on the compose network it must be the service name.

    So for a local emulator we keep the per-index port (5081+, assigned per
    index) and substitute the host we are configured to reach Pinecone at.
    A real Pinecone endpoint is returned untouched.
    """
    parsed = urlparse(advertised)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        return advertised

    reachable_host = urlparse(settings.pinecone_host).hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    return f"http://{reachable_host}{port}"


def _get_index():
    global _index
    if _index is None:
        desc = _pinecone_client.describe_index(settings.pinecone_index)
        _index = _pinecone_client.Index(host=_resolve_index_host(desc.host))
    return _index


def get_index_stats() -> int:
    """Total vectors in the index. Used by the health check to confirm the
    index exists and has been loaded."""
    return _get_index().describe_index_stats().total_vector_count


@lru_cache(maxsize=128)
def _embed_query(text: str) -> tuple[float, ...]:
    """Cached: a multi-company question issues the same retrieval query once
    per company, which would otherwise be N identical embedding round-trips.
    Embeddings are deterministic for a given text+model, so caching is safe.
    Returns a tuple (immutable) so a cached value can't be mutated by a caller."""
    response = _openai_client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
        dimensions=settings.openai_embedding_dim,
    )
    return tuple(response.data[0].embedding)


def search_filings(company: str, query: str, top_k: int = 5) -> list[dict]:
    """10-K chunks for `company` most relevant to `query`."""
    if company not in VECTOR_COVERAGE:
        return []

    index = _get_index()
    results = index.query(
        vector=list(_embed_query(query)),
        top_k=top_k,
        namespace="__default__",
        filter={"title": {"$eq": VECTOR_TITLE_BY_COMPANY[company]}},
        include_metadata=True,
    )

    return [
        {
            "score": match.score,
            "page": match.metadata.get("page"),
            "title": match.metadata.get("title"),
            "text": match.metadata.get("text"),
        }
        for match in results.matches
    ]
