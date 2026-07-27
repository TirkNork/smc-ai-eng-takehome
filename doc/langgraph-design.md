# Agent Design — LangGraph

The chatbot is a thin LangGraph state machine, not an autonomous ReAct agent.
Control flow is explicit so the **no-hallucination** requirement is enforced by
the graph rather than left to the model's discretion.

## Graph flow

<img src="img/langgraph-flow.svg" alt="LangGraph flow: classify branches to converse for chat, or to fetch_data, check_grounding, then synthesize or refuse" width="560">

## Nodes

| Node | Responsibility |
|------|----------------|
| `classify` | One LLM call with structured output (`app/agent/router.py`). First decides `kind` — **general** vs **data** — then rewrites a follow-up into a self-contained `standalone_question`, extracts companies (mapped onto the exact strings `financial_data` stores, e.g. Facebook→**Meta**, Alphabet→**Google**, "Bank of America"→**BankOfAmerica**) and any `years` the question names, picks a route (`sql`/`vector`/`hybrid`/`unsupported`), and emits an **English `retrieval_query`** for the filings search. The model is given the real company list read from Postgres. |
| `converse` | Answers a `general` message. Skips retrieval and the grounding gate entirely — there is nothing to fetch and no data claim to check. Given the real company list and coverage summary so it can describe its own scope from the data; forbidden from stating any figure, including one from an earlier answer. |
| `fetch_data` | Call `query_financials` (Postgres) and/or `search_filings` (Pinecone, filtered per company via `metadata.title`). Source failures are captured as `error`, not raised. |
| `check_grounding` | **The no-hallucination gate.** Derives coverage from what was *actually returned* per requested company, uniformly across all routes, and names any company that produced nothing in `missing_reason`. Also checks the fiscal **years** asked for: rows come back for every year on file, so a company matching never proved the requested year exists — a `sql` question naming only years the table lacks is refused outright. Refuses only when nothing at all came back; partial coverage proceeds with the gap disclosed. |
| `synthesize` | LLM composes the answer using retrieved SQL rows + filing chunks as the *only* allowed context. If `missing_reason` is set, the answer must state the gap — while still using every figure that *is* available. |
| `refuse` | LLM writes a short refusal in the question's own language, naming what's missing. A source **outage** is worded as "temporarily unavailable", never as "this data does not exist". |

## Chat vs data questions

`classify` decides `kind` before anything else, and a **general** message —
a greeting, or a question about the assistant itself or about what was said
earlier — branches straight to `converse`, never touching retrieval.

Two things make this split worth its own field rather than a fifth route value:

- **Order matters.** `kind` is the first field the model generates, so it is
  settled before the rewrite runs. Declared after it, *"what did I just ask?"*
  had already been turned into the previous question by the time the model
  could notice it was never a data question at all.
- **`kind` is not a coverage judgment.** Anything factual is `data`, even a
  share price we plainly do not hold. Whether we can serve it is decided by
  `route` (`unsupported`) and then by `check_grounding` — folding those two
  judgments together made the classifier route refusable questions into chat,
  where they were answered from the model's own knowledge instead of refused.

`converse` sees the transcript (the only node besides `classify` that does), so
its prompt forbids restating any figure from it. Every number a user is shown
comes from this turn's retrieval.

## Routing per baseline question

| Question | Route | Sources | Notes |
|----------|-------|---------|-------|
| **Q1** Apple net income 2022-2025 | `sql` | Postgres only | Pure structured lookup. |
| **Q2** Google vs Facebook revenue structure & strategy 2025 | `hybrid` | Postgres + vector | Two *separate* per-company filtered vector queries (Google, Meta) so results don't mix. |
| **Q3** Highest revenue growth among MSFT/AAPL/GOOG/FB + why | `hybrid` | Postgres + vector | Growth from SQL; "why" from 10-Ks — **but Microsoft has no filing**, so `check_grounding` sets a `missing_reason` and the answer must flag that the "why" is unavailable for Microsoft. |

## Conversation context

Follow-ups like *"แล้ว Google ล่ะ"* or *"why?"* need the earlier turns, but
history is also the easiest way to reintroduce hallucination: a figure quoted in
an earlier answer could be restated without being re-retrieved, and
`check_grounding` — which only inspects *this* turn's results — would never see
it.

So history is given exactly one job: **deciding what the question means, never
what the data is.**

- History lives in Postgres (`chat_sessions` / `chat_messages`, see
  `app/data_access/chat_history.py`), keyed by a per-user, per-conversation
  `session_id`. The client sends only `{question, session_id}` — never the
  transcript itself, so it can no longer put words in an earlier "assistant"
  turn's mouth the way a client-supplied history could.
- `POST /chat` loads that session's prior turns from the DB (ownership checked
  against the signed-in user first) and passes them into the graph as
  `history`. It reaches **`classify` only**. That node rewrites the question
  into `standalone_question`; every node after it sees that string and never
  the transcript. All data is re-retrieved from Postgres and Pinecone every
  turn — a stored message is never treated as a source of facts, only as
  context for what a follow-up means.
- Two failure modes the prompt could not fix reliably, so they are enforced in
  code instead:
  - the rewrite does not always keep the user's language, so `synthesize` and
    `refuse` are given the user's own wording as an explicit language anchor
    alongside the rewrite (`_question_block`).
  - with history in the prompt the classifier keeps returning earlier turns'
    companies, which would retrieve *their* data for a question that never
    asked about them — and count as grounded. `mentioned_in()` narrows the list
    to companies the resolved question actually names, and never to nothing.
- A session row is only created once a turn actually succeeds — a failed first
  message leaves no empty, title-only conversation behind.



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

`GraphState` (see `app/agent/state.py`) carries: `question`, `history`, `kind`,
`standalone_question`, `companies`, `years`, `route`, `retrieval_query`,
`sql_results`, `vector_results`, `grounded`, `missing_reason`, `error`,
`answer`.

`error` is deliberately separate from `missing_reason`: an unreachable
database must never be reported to the user as "this data does not exist",
which would be a false claim about the data itself.
