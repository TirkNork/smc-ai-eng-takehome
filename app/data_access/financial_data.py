"""Read-only access to the financial_data table.

The only query this project needs is "give me the rows for these companies
(optionally these years)" -- kept as one parameterized function rather than
a generic query builder, since an LLM-generated SQL string is a needless
injection surface for a single-table schema.
"""
from typing import Optional

from psycopg.rows import dict_row

from app.data_access.db import connection

COLUMNS = "company, ticker, sector, year, revenue, net_income, operating_income, gross_profit"


def query_financials(companies: list[str], years: Optional[list[int]] = None) -> list[dict]:
    """Rows for the given companies (exact match on `company`), optionally
    restricted to specific fiscal years. Returns [] if nothing matches --
    callers must treat that as "data not available", not silently proceed."""
    sql = f"select {COLUMNS} from financial_data where company = any(%(companies)s)"
    params: dict = {"companies": companies}

    if years:
        sql += " and year = any(%(years)s)"
        params["years"] = years

    sql += " order by company, year"

    with connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def coverage_summary() -> dict:
    """How many companies and which fiscal years the table actually holds.

    Read rather than hardcoded so the assistant describes its own scope from
    the data -- a constant in a prompt would quietly go stale the moment the
    fixture is reloaded with a different range.
    """
    with connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select count(distinct company) as companies,"
                " min(year) as first_year, max(year) as last_year from financial_data"
            )
            return cur.fetchone()


def list_known_companies() -> list[str]:
    """Every exact `company` string in the table. Company names are
    inconsistently formatted (e.g. "AmericanExpress" and "BankOfAmerica" have
    no spaces, but "Morgan Stanley" and "Eli Lilly" do) -- callers matching a
    natural-language company mention against this table should map onto one
    of these exact strings rather than guess a spelling."""
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select distinct company from financial_data order by company")
            return [row[0] for row in cur.fetchall()]
