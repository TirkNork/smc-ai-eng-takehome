# Database — ER Diagram

Structured financials live in a single PostgreSQL table loaded from
`data/financial_data.sql` (a `pg_dump`-style DDL prelude + `COPY` block).

## Current schema (as provided)

<img src="img/er-diagram.svg" alt="ER diagram of the financial_data table" width="360">

Column notes: `year` is fiscal year 2022-2025; `revenue`/`net_income`/
`operating_income`/`gross_profit` are USD; `net_income` may be negative;
**every monetary column is nullable** (see NULL counts below).

- **Rows:** 192 (~48 companies x 4 years, 2022-2025)
- **Grain:** one row per `(company, year)` — the natural key, though not
  declared as a constraint in the dump.
- **Units:** all monetary columns are raw USD `BIGINT` (e.g. `394328000000`).

## Observations / caveats

- **No primary key, unique, or foreign-key constraints.** The intended
  uniqueness is `(ticker, year)`. Add it when hardening the schema:
  ```sql
  ALTER TABLE financial_data ADD CONSTRAINT pk_financial_data
      PRIMARY KEY (ticker, year);
  ```
- **Denormalized on purpose.** `sector` repeats for every row of a company
  rather than living in a separate `companies` table. Acceptable for a small,
  read-only analytics workload; no need to normalize.
- **NULLs (`\N` in the dump) are widespread — including `revenue` itself.**
  Measured over all 192 rows:

  | Column | NULLs / 192 |
  |--------|:-----------:|
  | `gross_profit`     | 134 |
  | `operating_income` | 76  |
  | `revenue`          | 13  |
  | `net_income`       | 4   |

  Mostly the Finance sector, whose income statements don't map onto these
  lines. **`revenue` is NULL for all years of Goldman, Morgan Stanley, USB,
  and WellsFargo** — so a revenue-growth question touching those companies
  cannot be answered and must be refused, not guessed. Answers must always
  distinguish "value not available" from "value is zero/negative".
- **`net_income` can be negative** (e.g. AbbVie 2024 = -22M, Amazon 2022).
  Growth-rate math must handle negative and zero denominators.
- **Fiscal year is taken as-labeled.** Companies have different fiscal-year
  ends (Apple ends late September; Alphabet/Meta/Amazon end December). We do
  not reconcile calendar periods — `year` is used exactly as stored.

## Coverage vs. the vector store

The SQL table covers ~48 companies. The vector store (10-K text) covers only
**Alphabet, Amazon, Apple, Meta**. A company can therefore have financial
numbers but no filing text to ground a qualitative "why" answer — e.g.
Microsoft has SQL figures but no 10-K.
