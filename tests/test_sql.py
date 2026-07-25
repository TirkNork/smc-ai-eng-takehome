"""Requires the local Postgres to be up and loaded (docker compose up -d +
scripts/load_sql.sh) -- these hit the real database, not a mock."""
from app.data_access.sql import query_financials


def test_apple_all_years():
    rows = query_financials(["Apple"])
    assert len(rows) == 4
    by_year = {r["year"]: r for r in rows}
    assert by_year[2022]["net_income"] == 99803000000
    assert by_year[2023]["net_income"] == 96995000000
    assert by_year[2024]["net_income"] == 93736000000
    assert by_year[2025]["net_income"] == 112010000000


def test_year_filter():
    rows = query_financials(["Meta"], years=[2024, 2025])
    assert len(rows) == 2
    assert {r["year"] for r in rows} == {2024, 2025}


def test_null_columns_come_through_as_none():
    rows = query_financials(["Meta"], years=[2024])
    assert rows[0]["gross_profit"] is None


def test_multiple_companies():
    rows = query_financials(["Apple", "Meta"])
    assert {r["company"] for r in rows} == {"Apple", "Meta"}
    assert len(rows) == 8


def test_empty_company_list_returns_empty():
    assert query_financials([]) == []


def test_nonexistent_company_returns_empty():
    assert query_financials(["Nonexistent Corp"]) == []


def test_null_revenue_bank():
    # WellsFargo has NULL revenue for every year -- confirmed against the raw dump.
    # This must be surfaced as "data not available", not silently skipped.
    rows = query_financials(["WellsFargo"])
    assert len(rows) == 4
    assert all(r["revenue"] is None for r in rows)
