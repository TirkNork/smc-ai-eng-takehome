# 10-K Filing Structure (FY2025)

The `10k_filings/` folder holds four FY2025 annual reports: **Alphabet, Amazon,
Apple, Meta**. All four follow the **same standard SEC Form 10-K layout** —
four Parts, Items 1 through 16 — so the section *topics* are identical across
companies. What differs is length and how much each company elaborates a given
section (see the comparison table below).

These PDFs are the source of the qualitative / strategy text in the vector
store. Only these four companies have filing text; the other ~44 companies in
the SQL table have no 10-K here.

## Standard section map (all four companies)

Sections most useful to the chatbot's qualitative answers are marked **★**.

### Part I — the business and its risks
| Item | Topic | Relevance |
|------|-------|-----------|
| 1  | **Business** — what the company does, segments, products, revenue structure, strategy | ★★ core for Q2 (revenue structure & strategy) |
| 1A | **Risk Factors** — everything that could go wrong | ★ strengths/weaknesses, Q2 |
| 1B | Unresolved Staff Comments | — |
| 1C | Cybersecurity — risk management & governance | — |
| 2  | Properties — facilities, data centers, offices | — |
| 3  | Legal Proceedings | — |
| 4  | Mine Safety Disclosures (boilerplate; N/A for tech) | — |

### Part II — financial performance and analysis
| Item | Topic | Relevance |
|------|-------|-----------|
| 5  | Market for Registrant's Common Equity, Stockholder Matters, Issuer Purchases | — |
| 6  | [Reserved] (formerly Selected Financial Data) | — |
| 7  | **MD&A** — Management's Discussion & Analysis: *why* results changed, growth drivers, trends | ★★ core for Q3 ("main factors") |
| 7A | Quantitative & Qualitative Disclosures About Market Risk | — |
| 8  | **Financial Statements and Supplementary Data** — audited statements + notes | numbers come from SQL, not here |
| 9  | Changes in / Disagreements with Accountants | — |
| 9A | Controls and Procedures | — |
| 9B | Other Information | — |
| 9C | Foreign Jurisdictions that Prevent Inspections | — |

### Part III — governance
| Item | Topic |
|------|-------|
| 10 | Directors, Executive Officers, and Corporate Governance |
| 11 | Executive Compensation |
| 12 | Security Ownership of Certain Beneficial Owners and Management |
| 13 | Certain Relationships, Related Transactions, and Director Independence |
| 14 | Principal Accountant Fees and Services |

### Part IV — exhibits
| Item | Topic |
|------|-------|
| 15 | Exhibits, Financial Statement Schedules |
| 16 | Form 10-K Summary |

## Are they the same across companies?

**Yes for structure, no for size.** The topic list is identical (it's dictated
by SEC regulation). The volume differs substantially — Meta's filing is ~3x
Apple's, mostly from a far longer Risk Factors section.

| Company | Total pages | Item 1 Business (pg) | Item 1A Risk Factors (pg) | Item 7 MD&A / 7A (pg) | Item 8 Financials (pg) |
|---------|:-----------:|:--------------------:|:-------------------------:|:---------------------:|:----------------------:|
| Apple    | 77  | 1 | 5  | 7A @ 27 | 28 |
| Amazon   | 119 | 3 | 6  | 7A @ 31 | 33 |
| Alphabet | 156 | 3 | 9  | 7A @ 41 | 44 |
| Meta     | 215 | 6 | 12 | 7A @ 80 | 82 |

*(Page numbers are the printed labels from each filing's table of contents.)*
*Minor per-company wording differences exist — e.g. Amazon marks Item 6 as
"Reserved" explicitly; Apple omits it — but the numbered skeleton is the same.*

## What this means for retrieval

For the baseline questions, the useful text concentrates in three items:

- **Item 1 (Business)** → revenue structure, segments, business strategy — drives **Q2**.
- **Item 1A (Risk Factors)** → weaknesses / competitive pressures — supports **Q2**.
- **Item 7 (MD&A)** → the narrative on *why* revenue/income moved — drives the
  "main factors" part of **Q3**.

Items 3, 8–16 are mostly legal, governance, and raw financial statements. The
raw numbers there are already covered more cleanly by the SQL table, so the
vector store earns its keep primarily on Items 1, 1A, and 7.
