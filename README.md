# Financial Q&A Chatbot

A chat web app that answers questions about US public companies, grounded in
two data sources: a structured income-statement database (Postgres) and 10-K
filing text (Pinecone). Built for the Siametrics take-home assignment.

**The defining requirement is "no hallucination."** When the data needed to
answer a question isn't available, the assistant says so explicitly instead
of inventing a number or a reason. See [`doc/langgraph-design.md`](doc/langgraph-design.md)
for how that's enforced as control flow, not a prompt hope.

## Stack

| Layer | Choice |
|---|---|
| Agent | LangGraph — explicit state machine (`classify → fetch_data → check_grounding → synthesize \| refuse`, or `classify → converse` for messages that ask for no data), not an autonomous ReAct loop |
| Backend | FastAPI |
| Frontend | Streamlit |
| Structured data | PostgreSQL |
| Filing text | Pinecone (`pinecone-local`, in-memory, no persistence across container recreates) |
| Auth | JWT bearer tokens, username/password |
| LLM | OpenAI (`gpt-4o-mini` chat, `text-embedding-3-small` embeddings) |
| Tracing (optional) | LangSmith |

## Quickstart

### 1. Prerequisites

- Docker + Docker Compose
- An OpenAI API key

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and set:

- `OPENAI_API_KEY` — required for the agent to run at all.
- `JWT_SECRET` — required; the API refuses to start without one. Generate one with:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

Everything else in `.env.example` has a working default for local use.

### 3. Bring up the stack

```bash
docker compose up -d --build
```

This starts four containers: `postgres`, `pinecone` (in-memory Pinecone
emulator), `api` (FastAPI), `frontend` (Streamlit).

### 4. Load the data

The database and vector index start **empty** — Postgres has no `financial_data`
table and Pinecone has no vectors until you load them. Run once after the
containers are up:

```bash
# Structured financials (~48 companies, FY2022-2025)
./scripts/load_sql.sh
```

For the 10-K filing text there are **two options**. They are interchangeable
from the app's point of view — pick one, or load both and switch between them
(see [Switching between indexes](#switching-between-indexes)).

#### Option A — load the provided fixture (fast, no API key)

```bash
uv sync
uv run python scripts/load_vectors.py

# The fixture contains every chunk twice under different ids -- this removes
# the duplicates from the live index (see scripts/load_vector_note.txt for how
# that was found).
uv run python scripts/dedupe_vectors.py
```

Loads `data/pinecone_vectors.jsonl.gz` into `tenk-filings` — pre-embedded
chunks, cut every ~1000 characters.

#### Option B — build from the source PDFs (section-aware)

```bash
uv sync --extra ingest
uv run python scripts/build_vectors.py --dry-run              # inspect, no cost
uv run python scripts/build_vectors.py --index tenk-filings-v2
```

Parses `10k_filings/*.pdf` and chunks on the SEC item structure (Item 1, 1A,
7, ...) instead of by length, so no chunk spans two topics, chunks start and
end on sentence boundaries, and the print-to-PDF header/footer is stripped.
`--dry-run` reports the resulting chunk counts per company and per item.

Takes ~2 minutes and about $0.01 of embeddings, and needs `OPENAI_API_KEY`.
Full write-up: [`doc/vector-ingest.md`](doc/vector-ingest.md).

`uv sync` resolves extras per invocation rather than accumulating them, so
`--extra ingest` on its own *uninstalls* Streamlit. To keep both:

```bash
uv sync --extra frontend --extra ingest
```

> Building into a **separate index name** keeps the fixture index intact to
> compare against. Use `--clear` when rebuilding into an index you have already
> populated.

#### Switching between indexes

Nothing in the app is aware of which one is loaded — both satisfy the same
[contract](doc/vector-ingest.md#the-drop-in-contract). Point `PINECONE_INDEX`
at whichever you want.

Temporarily, for one command:

```bash
PINECONE_INDEX=tenk-filings-v2 uv run pytest tests/test_vector.py -q
```

Permanently — edit `PINECONE_INDEX` in `.env`, then recreate the containers.
`docker compose restart` is **not** enough: `env_file` is read when a container
is created, not when it starts.

```bash
docker compose up -d --force-recreate api frontend
```

Both indexes live inside the `pinecone` container, so an index built from the
host is immediately visible to `api` — no rebuild or copy needed.

To compare the two on retrieval quality:

```bash
uv run python scripts/judge_indexes.py
```

Re-run whichever loader you chose any time the `pinecone` container is
recreated — its index is in-memory only and does not survive a
`docker compose down` or a container recreate, unlike Postgres's `pgdata`
volume.

### 5. Open the app

**http://localhost:8501**

Create an account (or sign in) — the app requires a signed-in user. There's
no seed user; registration is open (`POST /auth/register`), matching what a
fresh clone needs to be usable without a setup script.

API docs (with a working "Authorize" button — sign in there too):
**http://localhost:8000/docs**

### Verify it's healthy

```bash
curl -s localhost:8000/health
```

```json
{"status":"ok","checks":{"postgres":"ok (49 companies)","pinecone":"ok (2034 vectors)"}}
```

The vector count reflects whichever index `PINECONE_INDEX` points at, so it
differs between the fixture and a `build_vectors.py` index.

If `pinecone` shows an error after any container recreate, re-run step 4's
Pinecone commands.

## Running tests

```bash
uv sync --extra frontend  # dev deps + pytest, once
uv run pytest -q
```

66 tests. Most run against the real local Postgres/Pinecone/OpenAI (no
mocks) — the stack from `docker compose up` must be running and loaded
first. A handful make real (cheap) OpenAI calls, consistent with the $10 API
budget for this assignment.

## The three baseline questions

Verified working end to end through the running app. Route and grounding
metadata included, since that's what the UI surfaces under "Sources" — the
whole point is that an answer's trustworthiness is visible, not asserted.

### Q1 — สรุป net income ปี2022-2025 ของบริษัท Apple

`route: sql` · `grounded: true`

> สรุป net income ของบริษัท Apple ในปี 2022-2025 มีดังนี้:
>
> - ปี 2022: 99,803,000,000 ดอลลาร์
> - ปี 2023: 96,995,000,000 ดอลลาร์
> - ปี 2024: 93,736,000,000 ดอลลาร์
> - ปี 2025: 112,010,000,000 ดอลลาร์

Pure structured lookup — no filing text needed, so it never leaves `sql`.

### Q2 — เปรียบเทียบโครงสร้างรายได้และกลยุทธ์ทางธุรกิจของ Google และ Facebook ปี2025

`route: hybrid` · `grounded: true` · `companies: [Google, Meta]`

> **โครงสร้างรายได้ปี 2025:**
> - **Google:** รายได้: 402,836,000,000 ดอลลาร์
> - **Meta:** รายได้: 200,966,000,000 ดอลลาร์ (โฆษณา 196,175,000,000 · อื่นๆ 2,584,000,000 · Reality Labs 2,207,000,000)
>
> **กลยุทธ์ทางธุรกิจปี 2025:**
> - **Google:** สร้างรายได้จากการโฆษณาออนไลน์, โซลูชันคลาวด์สำหรับลูกค้าองค์กร, และการขายผลิตภัณฑ์/บริการอื่นๆ...
> - **Meta:** มุ่งเน้นการสร้างรายได้จากโฆษณาและการขายผลิตภัณฑ์ฮาร์ดแวร์ เช่น Meta Quest และแว่นตา AI...

"Facebook" is normalized to "Meta" (the name `financial_data` actually
stores). Revenue from Postgres; strategy from two *separately filtered* 10-K
vector queries (Google, Meta), so retrieval results never cross-contaminate
between companies.

### Q3 — จากรายได้ของ Microsoft, Apple, Google, Facebook ปี2024-2025 บริษัทใดเติบโตสูงสุด และอะไรเป็นปัจจัยหลัก

`route: hybrid` · `grounded: true` · `missing_reason: "no 10-K filing text for: Microsoft"`

> จากรายได้ของบริษัท Microsoft, Apple, Google, Meta ในปี 2024-2025 บริษัทที่มีอัตราการเติบโตสูงสุดคือ **Meta** โดยมีรายได้ในปี 2024 ที่ 164,501 ล้านดอลลาร์ และในปี 2025 ที่ 200,966 ล้านดอลลาร์ เติบโต 22%
>
> ปัจจัยหลัก: การเพิ่มขึ้นของรายได้จากโฆษณา (จำนวนการแสดงโฆษณา +12%, ราคาเฉลี่ยต่อโฆษณา +9%)...
>
> Apple: 391,035 → 416,161 ล้านดอลลาร์ (+6%) · Google: 350,018 → 402,836 (+15%) · Microsoft: 245,122 → 281,724 (+15%)
>
> หมายเหตุ: ไม่มีข้อมูลจากการยื่น 10-K สำหรับ Microsoft ที่จะอธิบายปัจจัยการเติบโตของบริษัทนี้

**This is the deliberate trap in the assignment**: Microsoft has SQL figures
but no 10-K filing in the vector store. The correct behavior — and what
actually happens — is answering the *growth ranking* (which needs only SQL,
so Microsoft is included and correctly not the winner) while explicitly
flagging that Microsoft's growth *driver* can't be explained, rather than
either silently omitting Microsoft or inventing a qualitative reason for it.

## Project layout

```
app/
  agent/          LangGraph state machine (classify, converse, fetch_data, check_grounding, synthesize, refuse)
  api/routes/      FastAPI routes: health, auth, chat, sessions
  auth/            Password hashing + JWT encode/decode (pure, no DB/FastAPI)
  data_access/     db.py (connection pool) + one module per table/source:
                   financial_data.py, vector.py, users.py, chat_history.py, companies.py
  schemas/         Pydantic request/response models
  config.py        Single source of truth for env vars
  main.py          FastAPI app + lifespan
frontend/
  app.py           Streamlit chat UI
  auth.py          Sign-in/register gate
  api_client.py    HTTP client for the backend
scripts/
  load_sql.sh          Load financial_data.sql into Postgres (idempotent)
  load_vectors.py      Load the provided 10-K vector fixture (--clear to wipe+reload)
  dedupe_vectors.py    Remove the fixture's duplicate vectors
  build_vectors.py     Alternative: build the index from 10k_filings/*.pdf, chunked by SEC section
  judge_indexes.py     Pairwise LLM-as-judge comparison of two indexes
tests/             66 tests, mostly against the real local stack (no mocks)
doc/               Design docs: LangGraph flow, DB schema, auth flow, 10-K structure,
                   vector ingestion, financial-terms glossary
data/              Provided fixtures (financial_data.sql, pinecone_vectors.jsonl.gz)
10k_filings/       The four source 10-K PDFs (input to build_vectors.py)
```

## Design notes

Longer write-ups of specific decisions, for anyone extending this:

- [`doc/langgraph-design.md`](doc/langgraph-design.md) — the graph, the
  no-hallucination gate, and how multi-turn conversation context is resolved
  without ever treating a stored message as a source of facts.
- [`doc/database-er-diagram.md`](doc/database-er-diagram.md) — all four
  tables: the provided `financial_data` (its NULLs, and why some companies
  like Goldman and Morgan Stanley can't answer revenue questions at all) plus
  `users` → `chat_sessions` → `chat_messages`, the app's own auth and chat
  history schema.
- [`doc/auth-flow.md`](doc/auth-flow.md) — register, login, and the stateless
  JWT bearer token: what the token carries (and deliberately does not), why
  ownership is enforced at the data-access layer rather than in the token, and
  an honest list of what the scheme does not do.
- [`doc/10k-structure.md`](doc/10k-structure.md) — how the four 10-K filings
  are structured and chunked.
- [`doc/vector-ingest.md`](doc/vector-ingest.md) — the section-aware ingestion
  pipeline: what was wrong with fixed-length chunking, how filing sections are
  detected without being fooled by the table of contents or by
  cross-references, the contract that makes a rebuilt index a drop-in
  replacement, and an honest account of what the LLM-as-judge comparison did
  and did not establish.
- [`doc/keyword.md`](doc/keyword.md) — glossary (in Thai) of the income-statement
  terms in `financial_data`: what each one means, how it is derived, and what it
  tells you about the business.


