"""Query-time embedding + Pinecone search, filtered to one company's 10-K.

Returns [] immediately for a company with no filing in the vector store
(see companies.VECTOR_COVERAGE) rather than spending an embedding call on a
search that can't return anything -- callers must treat [] as "data not
available", not silently proceed.
"""
from openai import OpenAI
from pinecone import Pinecone

from app.config import settings
from app.data_access.companies import VECTOR_COVERAGE, VECTOR_TITLE_BY_COMPANY

_openai_client = OpenAI(api_key=settings.openai_api_key)
_pinecone_client = Pinecone(api_key=settings.pinecone_api_key, host=settings.pinecone_host)
_index = None


def _get_index():
    global _index
    if _index is None:
        desc = _pinecone_client.describe_index(settings.pinecone_index)
        # pinecone-local advertises https in describe_index but only serves
        # plain HTTP on the per-index port -- force http or the client's TLS
        # handshake fails.
        host = desc.host.replace("https://", "http://")
        _index = _pinecone_client.Index(host=host)
    return _index


def _embed_query(text: str) -> list[float]:
    response = _openai_client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
        dimensions=settings.openai_embedding_dim,
    )
    return response.data[0].embedding


def search_filings(company: str, query: str, top_k: int = 5) -> list[dict]:
    """10-K chunks for `company` most relevant to `query`."""
    if company not in VECTOR_COVERAGE:
        return []

    vector = _embed_query(query)
    index = _get_index()
    results = index.query(
        vector=vector,
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
