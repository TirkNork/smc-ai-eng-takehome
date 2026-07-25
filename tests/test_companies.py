from app.data_access.companies import (
    VECTOR_COVERAGE,
    VECTOR_TITLE_BY_COMPANY,
    normalize_company,
)


def test_normalize_matches_sql_company_column():
    # SQL stores "Google" and "Meta", not "Alphabet"/"Facebook" -- confirmed
    # against the live financial_data table.
    assert normalize_company("google") == "Google"
    assert normalize_company("alphabet") == "Google"
    assert normalize_company("facebook") == "Meta"
    assert normalize_company("meta") == "Meta"
    assert normalize_company("apple") == "Apple"
    assert normalize_company("amazon") == "Amazon"
    assert normalize_company("microsoft") == "Microsoft"


def test_normalize_is_case_and_whitespace_insensitive():
    assert normalize_company("  Facebook  ") == "Meta"
    assert normalize_company("GOOGLE") == "Google"


def test_normalize_passes_through_unknown_names():
    assert normalize_company("Tesla") == "Tesla"


def test_vector_coverage_is_exactly_the_four_filed_companies():
    assert VECTOR_COVERAGE == {"Apple", "Amazon", "Google", "Meta"}


def test_every_covered_company_has_a_title_mapping():
    assert set(VECTOR_TITLE_BY_COMPANY) == VECTOR_COVERAGE


def test_microsoft_has_no_vector_coverage():
    # The deliberate trap in Q3: SQL has Microsoft figures, no 10-K to ground "why".
    assert "Microsoft" not in VECTOR_COVERAGE
