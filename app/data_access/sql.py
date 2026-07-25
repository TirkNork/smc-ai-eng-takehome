"""Read-only access to the financial_data table.

The only query this project needs is "give me the rows for these companies
(optionally these years)" -- kept as one parameterized function rather than
a generic query builder, since an LLM-generated SQL string is a needless
injection surface for a single-table schema.
"""
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from app.config import settings

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

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
