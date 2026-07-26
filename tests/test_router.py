"""Requires a real OPENAI_API_KEY and the local Postgres (the classifier is
given the real company list). One LLM call per test."""
from app.agent.router import classify_question


def test_numeric_question_routes_to_sql():
    result = classify_question({"question": "สรุป net income ปี2022-2025 ของบริษัท Apple"})
    assert result["companies"] == ["Apple"]
    assert result["route"] == "sql"


def test_qualitative_question_routes_to_vector():
    # The keyword-based router could never produce this route.
    result = classify_question({"question": "What is driving Meta's success in the market lately?"})
    assert result["companies"] == ["Meta"]
    assert result["route"] == "vector"


def test_mixed_question_routes_to_hybrid():
    result = classify_question(
        {
            "question": "จากรายได้ของบริษัท Microsoft, Apple, Google, Facebook ในปี2024-2025 "
            "บริษัทใดที่มีอัตราการเติบโตต่อสูงสุด และอะไรเป็นปัจจัยหลัก"
        }
    )
    assert result["route"] == "hybrid"
    assert set(result["companies"]) == {"Apple", "Google", "Meta", "Microsoft"}


def test_aliases_map_to_sql_table_names():
    result = classify_question({"question": "Compare Facebook and Alphabet revenue"})
    assert set(result["companies"]) == {"Meta", "Google"}


def test_irregularly_spelled_companies_map_exactly():
    # financial_data stores these without spaces -- a natural-language
    # mention has to be mapped or the SQL lookup silently returns nothing.
    result = classify_question({"question": "Compare Bank of America and Capital One revenue in 2024"})
    assert set(result["companies"]) == {"BankOfAmerica", "CapitalOne"}


def test_question_without_a_company_is_unsupported():
    result = classify_question({"question": "What is a good P/E ratio?"})
    assert result["companies"] == []
    assert result["route"] == "unsupported"


def test_retrieval_query_is_english_for_a_thai_question():
    result = classify_question(
        {"question": "เปรียบเทียบโครงสร้างรายได้และกลยุทธ์ทางธุรกิจของ Google และ Facebook"}
    )
    query = result["retrieval_query"]
    assert query
    # The filings are English; a Thai query embeds poorly against them.
    assert query.isascii()
