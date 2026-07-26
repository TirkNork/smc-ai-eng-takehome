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

# Reverse lookup, so grounding checks can derive which companies were
# ACTUALLY retrieved from the chunks returned, rather than trusting
# VECTOR_COVERAGE (a constant that can drift from what the index holds).
COMPANY_BY_VECTOR_TITLE = {title: company for company, title in VECTOR_TITLE_BY_COMPANY.items()}


def normalize_company(name: str) -> str:
    return COMPANY_ALIASES.get(name.strip().lower(), name.strip())


def _squash(text: str) -> str:
    """Lowercase and drop spaces, so "American Express" in a question matches
    "AmericanExpress" as the table spells it."""
    return "".join(text.lower().split())


def mentioned_in(companies: list[str], text: str) -> list[str]:
    """Narrow `companies` to those actually named in `text`.

    A follow-up question carries its conversation in the prompt, so the
    classifier tends to keep returning companies from earlier turns. Left
    alone, a question about a company we hold nothing for would still retrieve
    the earlier companies' data and count as grounded.

    Returns `companies` unchanged when the match finds nothing -- a company
    named by ticker or an unlisted spelling must not be dropped, so this only
    ever narrows, never empties.
    """
    haystack = _squash(text)

    def named(company: str) -> bool:
        # Its canonical name, or any alias resolving to it -- a question saying
        # "Facebook" names Meta.
        spellings = [company] + [a for a, c in COMPANY_ALIASES.items() if c == company]
        return any(_squash(s) in haystack for s in spellings)

    return [c for c in companies if named(c)] or companies
