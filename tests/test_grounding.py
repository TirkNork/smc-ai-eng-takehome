"""check_grounding is the no-hallucination gate -- pure logic over state, so
these run without a DB, Pinecone, or any LLM call."""
from app.agent.nodes import _question_block, check_grounding

APPLE_ROW = {"company": "Apple", "year": 2025, "revenue": 416161000000}
APPLE_CHUNK = {"title": "aapl-20250927", "page": 1, "text": "...", "score": 0.5}
GOOGLE_CHUNK = {"title": "goog-20251231", "page": 1, "text": "...", "score": 0.5}


def test_unsupported_route_refuses():
    result = check_grounding({"route": "unsupported", "companies": []})
    assert result["grounded"] is False
    assert result["missing_reason"]


def test_sql_route_with_no_rows_refuses():
    result = check_grounding({"route": "sql", "companies": ["Rivian"], "sql_results": []})
    assert result["grounded"] is False


def test_sql_route_names_company_with_no_rows():
    # Regression: partial SQL coverage used to pass through with
    # missing_reason=None, silently dropping the company from the answer.
    result = check_grounding(
        {"route": "sql", "companies": ["Apple", "Rivian"], "sql_results": [APPLE_ROW]}
    )
    assert result["grounded"] is True
    assert "Rivian" in result["missing_reason"]
    assert "Apple" not in result["missing_reason"]


def test_vector_route_names_company_with_no_filing():
    # Regression: same silent-drop bug on the vector route.
    result = check_grounding(
        {"route": "vector", "companies": ["Apple", "Nvidia"], "vector_results": [APPLE_CHUNK]}
    )
    assert result["grounded"] is True
    assert "Nvidia" in result["missing_reason"]


def test_hybrid_flags_missing_filing_but_stays_grounded():
    # The Q3 case: Microsoft has SQL figures but no 10-K to explain "why".
    result = check_grounding(
        {
            "route": "hybrid",
            "companies": ["Google", "Microsoft"],
            "sql_results": [{"company": "Google"}, {"company": "Microsoft"}],
            "vector_results": [GOOGLE_CHUNK],
        }
    )
    assert result["grounded"] is True
    assert "Microsoft" in result["missing_reason"]
    assert "10-K" in result["missing_reason"]


def test_full_coverage_has_no_missing_reason():
    result = check_grounding(
        {
            "route": "hybrid",
            "companies": ["Apple"],
            "sql_results": [APPLE_ROW],
            "vector_results": [APPLE_CHUNK],
        }
    )
    assert result["grounded"] is True
    assert result["missing_reason"] is None


def test_coverage_derived_from_results_not_a_constant():
    # Apple IS in VECTOR_COVERAGE, but nothing came back for it (e.g. empty
    # index). The gate must trust actual results, not the constant.
    result = check_grounding({"route": "vector", "companies": ["Apple"], "vector_results": []})
    assert result["grounded"] is False
    assert "Apple" in result["missing_reason"]


def test_source_outage_is_not_reported_as_missing_data():
    result = check_grounding(
        {"route": "sql", "companies": ["Apple"], "error": "could not reach the financial database (OperationalError)"}
    )
    assert result["grounded"] is False
    assert "could not reach" in result["missing_reason"]


def test_question_block_is_just_the_question_on_a_first_turn():
    # Nothing was rewritten, so there is no second wording to disambiguate.
    block = _question_block({"question": "Apple net income 2025", "standalone_question": "Apple net income 2025"})
    assert block == "Question: Apple net income 2025"


def test_question_block_anchors_the_reply_language_to_the_users_own_wording():
    # The rewrite is not reliably in the user's language, and the reply must be.
    block = _question_block(
        {"question": "why?", "standalone_question": "ทำไมรายได้ของ Meta ถึงเติบโต"}
    )
    assert "why?" in block
    assert "ทำไมรายได้ของ Meta ถึงเติบโต" in block
    assert "REPLY IN THIS LANGUAGE" in block
