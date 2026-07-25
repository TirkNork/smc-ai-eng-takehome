"""Requires a real OPENAI_API_KEY in .env and the local Pinecone index
loaded (scripts/load_vectors.py) -- these hit the real embedding API and
the real vector store, not mocks."""
from app.data_access.companies import VECTOR_TITLE_BY_COMPANY
from app.data_access.vector import search_filings


def test_uncovered_company_returns_empty_without_api_call():
    # Microsoft has SQL figures but no 10-K -- must short-circuit before
    # spending an embedding call, not just return no matches.
    results = search_filings("Microsoft", "why did revenue grow")
    assert results == []


def test_apple_returns_relevant_results():
    results = search_filings("Apple", "business strategy and revenue segments", top_k=3)
    assert len(results) == 3
    for r in results:
        assert r["title"] == VECTOR_TITLE_BY_COMPANY["Apple"]
        assert isinstance(r["text"], str) and r["text"]
        assert isinstance(r["page"], int)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), "results must be ranked best-first"


def test_google_and_meta_do_not_cross_contaminate():
    google_results = search_filings("Google", "revenue structure and business strategy", top_k=5)
    meta_results = search_filings("Meta", "revenue structure and business strategy", top_k=5)

    assert google_results and meta_results
    assert all(r["title"] == VECTOR_TITLE_BY_COMPANY["Google"] for r in google_results)
    assert all(r["title"] == VECTOR_TITLE_BY_COMPANY["Meta"] for r in meta_results)
