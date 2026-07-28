# Vector Ingestion: Section-Aware Chunking

How `scripts/build_vectors.py` turns the four 10-K PDFs into the vector index,
and why it exists alongside the provided fixture.

Companion to [`10k-structure.md`](10k-structure.md), which describes the filing
structure this pipeline relies on.

## Two ways to populate the index

| | `load_vectors.py` (provided) | `build_vectors.py` (this doc) |
|---|---|---|
| Source | `data/pinecone_vectors.jsonl.gz` | `10k_filings/*.pdf` |
| Chunking | fixed ~1000 characters | SEC item sections, sentence boundaries |
| Embedding | pre-computed in the fixture | computed at build time (~$0.01) |
| Runtime | seconds | ~2 minutes |
| Needs `OPENAI_API_KEY` | no | yes |

Both produce an index the app can query without any code change — see
[The drop-in contract](#the-drop-in-contract).

## Why

The fixture chunks the filings every ~1000 characters with no regard for
content, which causes three separate problems:

1. **Topic straddling.** A cut every 1000 characters lands wherever it lands,
   so a chunk routinely covers the end of one subject and the start of the
   next. Its embedding is the average of both, which matches neither well.
2. **Fragments.** Chunks routinely open mid-clause (`"d not be considered a
   complete statement..."`). Even when retrieved, the fact they carry is hard
   to use and hard to cite.
3. **Boilerplate.** These PDFs are browser prints, and every page carries a
   timestamp line, a `file:///...` path, and a running footer. Chunks pick that
   furniture up; some contain nothing else, and they occupy `top_k` slots that
   should hold filing text.

## Pipeline

```
PDF ─▶ extract ─▶ clean ─▶ detect sections ─▶ chunk ─▶ dedupe ─▶ embed ─▶ upsert
```

### 1. Extract

`pypdf`, page by page, NFKD-normalised. The normalisation matters: these files
carry ligature codepoints, so `significant` is stored as `signiﬁcant` and
`file:///` as `ﬁle:///`. Left alone they are embedded — and keyword-matched —
as characters no query will ever contain.

### 2. Clean

Boilerplate is detected, not hardcoded: a line is dropped when its
**digit-normalised** form appears on more than 20% of pages.

Normalising digits first is the whole trick. The three boilerplate families
differ per page only by their page number:

```
4/20/26, 12:05 PM aapl-20250927            →  #/#/#, #:# PM aapl-#
file:///Users/.../Apple_10K.htm 11/77      →  file:///Users/.../Apple_10K.htm #/#
Apple Inc. | 2025 Form 10-K | 7            →  Apple Inc. | # Form #-K | #
```

Counting raw lines finds only the first. After normalisation all three collapse
to a single repeated form and are removed together.

### 3. Detect sections

Form 10-K structure is fixed by SEC regulation and identical across all four
filings, so sections are found with a regex on `Item N.` rather than inferred
from embeddings. Cheaper, and exact.

Two things make it harder than it looks.

**The table of contents.** Every filing's TOC lists all 23 items on one page.
A page carrying 8 or more item headings is treated as the TOC and skipped; no
body page comes close to that.

**Cross-references.** Filings refer to their own items in body text ("as
discussed in Item 8"), and the regex cannot tell a reference from a heading.
Real headings are the longest run appearing in regulation order, so a **longest
increasing subsequence** over the item key selects them.

Taking each next-larger item greedily instead would be wrong, and Meta shows
why:

```
page 117   Item 8    ← a cross-reference
page 132   Item 7A   ← the real heading
page 135   Item 8    ← the real heading
```

A greedy pass locks onto the reference on page 117 and must then discard both
genuine headings after it. LIS recovers the correct chain — all 23 items, in
all four filings.

### 4. Chunk

Chunks are cut **within a section only**, so none spans two items. Target ~900
characters, ~130 characters of overlap, cut at a sentence boundary at both the
start and the end of every chunk.

Both ends matter. Cutting cleanly at the end but stepping back a fixed 130
characters for the overlap lands the *next* chunk mid-clause — which is half
the fragment problem left in place.

What counts as a sentence boundary is narrower than it looks; see the comment
on `_SENTENCE_END` in the script.

### 5. Dedupe

By SHA-1 of the whitespace-normalised, lowercased text, at write time. The
fixture needed a separate cleanup pass (`scripts/dedupe_vectors.py`) because
its duplicates were already in the index; building our own means never writing
them.

### 6. Embed and upsert

`text-embedding-3-small` at 512 dimensions — read from `app.config.settings`,
not re-read from the environment, so the ingest side cannot drift from the
query side. Namespace `__default__`.

Chunk ids are deterministic (`aapl-20250927-1A-0025`), so a re-run overwrites
rather than accumulating a second copy.

> **`--clear` is required when rebuilding after a chunking change.** Ids carry
> a per-section running number, so a build producing fewer chunks leaves the
> surplus ids from the previous build behind, un-overwritten.

## The drop-in contract

`app/data_access/vector.py` projects a match down to four fields — `score`,
`title`, `page`, `text`. Everything else is invisible to the app. So an index
built by this script is a drop-in replacement as long as eight things hold:

| # | Must be | Read by | If wrong |
|---|---|---|---|
| 1 | index name matches `PINECONE_INDEX` | `config.py:16` | index not found (loud) |
| 2 | dimension 512, metric cosine | `config.py:20` | upsert error (loud) |
| 3 | model `text-embedding-3-small` | `config.py:19` | **silently** useless matches |
| 4 | namespace `__default__` | `vector.py:81` | **silently** returns `[]` |
| 5 | `metadata.title` ∈ the fixture's four values | `companies.py:24` | **silently** refuses |
| 6 | `metadata.text` non-empty str | `nodes.py:158` | empty context |
| 7 | `metadata.page` an `int` | `test_vector.py:22` | test failure |
| 8 | ids unique | — | chunks overwrite each other |

Items 3, 4 and 5 are the dangerous ones: they raise nothing. The chain for a
wrong `title` is `filter matches nothing → search_filings returns [] →
check_grounding reports "no 10-K filing text for: Apple" → the app refuses`,
which looks exactly like a company genuinely not being covered.

Because titles cannot be derived from filenames — `Alphabet_10K_FY2025.pdf`
holds the filing titled `goog-20251231` — they are pinned in `FILINGS` at the
top of the script.

### Extra metadata

Beyond the contract, each vector also carries:

```python
"company": "Apple",
"item":    "1A",
"section": "Risk Factors",
```

The app ignores all of it today. It exists so section filtering
(`filter={"item": {"$in": ["1A"]}}` for a risk question) and richer citations
(`[Apple 10-K, Item 1A Risk Factors, p.25]` instead of `[aapl-20250927 p.25]`)
can be added later without another re-ingest.

## Evaluation

`scripts/judge_indexes.py` compares two indexes with a pairwise LLM judge over
a fixed question set. Cosine score cannot be used for this — it moves with
chunk size, so any chunking change shifts it for reasons unrelated to quality.

Three controls:

- **Position bias.** Judges favour whichever set is shown first, so every pair
  is judged twice with the sides swapped. A win counts only if it survives the
  swap.
- **Blind.** Sets are labelled A/B; the section metadata that would identify
  the new index is withheld.
- **Shared query embedding.** Both sides are searched with the identical query
  vector.

### What it found, and what it did not

Judged with `gpt-4o` over 8 questions, the new index won 3, lost 0, tied 5.

**Do not read that as a 3× improvement.** Four of the eight questions came back
*position-dependent* — the judge picked whichever set was in slot A both times.
Reordering the response schema so the per-set analysis is generated before the
verdict did not reduce that rate. At this granularity `gpt-4o` is not a
reliable judge for this comparison, and the aggregate is weak evidence.

Its actual value was finding one concrete bug. On "revenue structure across
products and services", the *old* index won position-stably across two
independent runs, with the same reason both times: it retrieved Apple's net
sales by product category, and the new index did not. That was the colon
splitting table captions off their tables. After the fix, that question is a
tie — no other change.

A counting metric would never have found that; the position-bias control is
what made the signal legible as a real one rather than noise.

There is no golden set behind any of this, so there is no deterministic
regression test for retrieval quality either. Both indexes still exist, so one
can be added later and run against both.
