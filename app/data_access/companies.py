"""Canonical company names shared between the SQL table and the vector store.

The financial_data table stores "Google" (not "Alphabet") and "Meta" (not
"Facebook") in its `company` column -- confirmed against the live table.
Every alias below resolves to those exact strings so query_financials'
`company = ANY(%s)` match works.
"""

COMPANY_ALIASES = {
    "apple": "Apple",
    "amazon": "Amazon",
    "google": "Google",
    "alphabet": "Google",
    "facebook": "Meta",
    "meta": "Meta",
    "microsoft": "Microsoft",
}

# Only these four companies have 10-K text in the vector store; the SQL
# table covers ~48. See doc/database-er-diagram.md.
VECTOR_COVERAGE = {"Apple", "Amazon", "Google", "Meta"}

# metadata.title value per company's filing in the Pinecone index.
VECTOR_TITLE_BY_COMPANY = {
    "Apple": "aapl-20250927",
    "Amazon": "amzn-20251231",
    "Google": "goog-20251231",
    "Meta": "meta-20251231",
}


def normalize_company(name: str) -> str:
    return COMPANY_ALIASES.get(name.strip().lower(), name.strip())
