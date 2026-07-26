# Agent Design — LangGraph

The chatbot is a thin LangGraph state machine, not an autonomous ReAct agent.
Control flow is explicit so the **no-hallucination** requirement is enforced by
the graph rather than left to the model's discretion.

## Graph flow

<img src="img/langgraph-flow.svg" alt="LangGraph flow: classify, fetch_data, check_grounding, synthesize or refuse" width="420">

## Nodes

| Node | Responsibility |
|------|----------------|
| `classify` | One LLM call with structured output (`app/agent/router.py`). Extracts companies — mapped onto the exact strings `financial_data` stores, e.g. Facebook→**Meta**, Alphabet→**Google**, "Bank of America"→**BankOfAmerica** — picks a route (`sql`/`vector`/`hybrid`/`unsupported`), and emits an **English `retrieval_query`** for the filings search. The model is given the real company list read from Postgres. |
| `fetch_data` | Call `query_financials` (Postgres) and/or `search_filings` (Pinecone, filtered per company via `metadata.title`). Source failures are captured as `error`, not raised. |
| `check_grounding` | **The no-hallucination gate.** Derives coverage from what was *actually returned* per requested company, uniformly across all routes, and names any company that produced nothing in `missing_reason`. Refuses only when nothing at all came back; partial coverage proceeds with the gap disclosed. |
| `synthesize` | LLM composes the answer using retrieved SQL rows + filing chunks as the *only* allowed context. If `missing_reason` is set, the answer must state the gap — while still using every figure that *is* available. |
| `refuse` | LLM writes a short refusal in the question's own language, naming what's missing. A source **outage** is worded as "temporarily unavailable", never as "this data does not exist". |

## Routing per baseline question

| Question | Route | Sources | Notes |
|----------|-------|---------|-------|
| **Q1** Apple net income 2022-2025 | `sql` | Postgres only | Pure structured lookup. |
| **Q2** Google vs Facebook revenue structure & strategy 2025 | `hybrid` | Postgres + vector | Two *separate* per-company filtered vector queries (Google, Meta) so results don't mix. |
| **Q3** Highest revenue growth among MSFT/AAPL/GOOG/FB + why | `hybrid` | Postgres + vector | Growth from SQL; "why" from 10-Ks — **but Microsoft has no filing**, so `check_grounding` sets a `missing_reason` and the answer must flag that the "why" is unavailable for Microsoft. |

## Why this shape

- **Grounding is a control-flow property**, so it's an explicit node/edge we own
  — not a hope that a tool-calling loop decides correctly.
- The **data-access seam** (`app/data_access/`) is isolated from graph wiring,
  so new sources, new routes plug in without rewrites.
- **Routing is semantic, not lexical.** An earlier keyword-matching version
  could not express the `vector` route at all and broke on any paraphrase.
- **LangSmith tracing** wraps the whole graph, giving a visible audit trail from
  question → routing → retrieval → grounded answer. Enabled via
  `LANGSMITH_TRACING`/`LANGSMITH_API_KEY`; the app runs normally without them.

## State

`GraphState` (see `app/agent/state.py`) carries: `question`, `companies`,
`route`, `retrieval_query`, `sql_results`, `vector_results`, `grounded`,
`missing_reason`, `error`, `answer`.

`error` is deliberately separate from `missing_reason`: an unreachable
database must never be reported to the user as "this data does not exist",
which would be a false claim about the data itself.
