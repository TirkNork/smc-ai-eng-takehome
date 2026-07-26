from app.data_access.companies import (
    VECTOR_COVERAGE,
    VECTOR_TITLE_BY_COMPANY,
    mentioned_in,
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


def test_mentioned_in_drops_companies_carried_over_from_earlier_turns():
    # The follow-up "แล้ว Microsoft ล่ะ" resolves to a Microsoft-only question,
    # but the classifier keeps returning the companies of the previous turn.
    # Left in, their filings would be retrieved and the answer would count as
    # grounded even though nothing covers the company actually asked about.
    assert mentioned_in(
        ["Google", "Meta", "Microsoft"], "กลยุทธ์ธุรกิจของ Microsoft ปี 2025 เป็นอย่างไร"
    ) == ["Microsoft"]


def test_mentioned_in_matches_each_company_by_its_own_alias():
    # Google matches its canonical name and Meta only via "Facebook" -- one
    # must not mask the other.
    assert mentioned_in(["Google", "Meta"], "compare Google and Facebook") == ["Google", "Meta"]


def test_mentioned_in_ignores_spacing_differences():
    # financial_data spells it "AmericanExpress"; a question would not.
    assert mentioned_in(["AmericanExpress"], "American Express revenue 2025") == [
        "AmericanExpress"
    ]


def test_mentioned_in_keeps_everything_when_nothing_matches():
    # Only ever narrows: a company named by ticker or an unlisted spelling must
    # survive rather than leave the question with no subject at all.
    assert mentioned_in(["Apple"], "how did AAPL do last year") == ["Apple"]


def test_mentioned_in_is_a_noop_on_an_empty_list():
    assert mentioned_in([], "no company here") == []
