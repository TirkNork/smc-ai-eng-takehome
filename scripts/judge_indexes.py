"""Pairwise LLM-as-judge comparison of two vector indexes.

Answers the only question that matters after a chunking change: for the same
question, does the new index retrieve excerpts that better support an answer?

Why pairwise, and not a score per index
---------------------------------------
Cosine score cannot be compared across indexes -- it moves with chunk size.
A chunk covering three topics has an embedding averaged across them, so it
scores lower against a single-topic query than a shorter, purer chunk does,
regardless of which is actually more useful. Any chunking change moves the
scores for reasons unrelated to quality.

Asking a judge for an absolute 0-10 per index has its own problem: LLM
absolute ratings cluster in a narrow band and drift between runs, which
buries the difference we are trying to measure. Relative judgements are far
more stable, so this asks only "A or B".

Three controls make the verdicts trustworthy:

  * position bias -- judges favour whichever set is shown first, so every
    pair is judged twice with the sides swapped. A win counts only if it
    survives the swap; disagreement is recorded as a tie, because that is
    the judge tracking position rather than content.
  * blind -- the sets are labelled A/B only. Told which one is "new", a
    judge will tend to prefer it.
  * shared query embedding -- both sides are searched with the identical
    query vector, so nothing varies but the chunking.

The judge model is deliberately not settings.openai_chat_model: the app runs
on a small model, and a small model is an unreliable judge.

Usage:
    uv run python scripts/judge_indexes.py
    uv run python scripts/judge_indexes.py --index-b tenk-filings-v2 --top-k 5
    uv run python scripts/judge_indexes.py --dry-run   # show retrieval, no judging
"""
import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pinecone import Pinecone
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent

load_dotenv()
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.data_access.companies import VECTOR_TITLE_BY_COMPANY  # noqa: E402
from app.data_access.vector import _embed_query, _resolve_index_host  # noqa: E402

# Questions the app is actually meant to answer: qualitative material that
# has to come from the filing text rather than the SQL figures.
QUESTIONS = [
    ("Meta", "risks related to artificial intelligence and its regulation"),
    ("Apple", "supply chain concentration and component sourcing risk"),
    ("Amazon", "what drives AWS revenue growth"),
    ("Google", "cloud business strategy and competitive position"),
    ("Meta", "how the advertising business generates revenue"),
    ("Apple", "revenue structure across products and services"),
    ("Amazon", "main factors affecting operating income"),
    ("Google", "capital expenditure on data centers and AI infrastructure"),
]

JUDGE_SYSTEM_PROMPT = """You are evaluating retrieval quality for a financial question-answering
system grounded in 10-K filings.

You are given a question and two sets of excerpts, A and B, retrieved for
that same question from the same filing by two different systems. Judge which
set would better support answering the question. Do not answer the question
yourself, and do not reward a set for being longer.

Criteria, in priority order:

1. Coverage -- does the set actually contain the facts needed to answer?
2. Usability -- are excerpts coherent and self-contained, or do they begin or
   end mid-sentence so the fact they carry cannot be relied on?
3. Focus -- how much of the set is irrelevant to the question: boilerplate,
   page furniture, cross-references, or unrelated sections of the filing?

Work through A and B separately against these criteria, citing excerpt
numbers, before deciding. The order the sets are presented in carries no
meaning and must not influence the verdict.

Answer "tie" only when the two sets are genuinely equivalent on these
criteria, not merely when both are imperfect."""


class Verdict(BaseModel):
    """Field order is load-bearing.

    Structured output is generated field by field, so a schema that puts
    `winner` first has the model commit to a side before it has examined
    anything, and `reason` then rationalises the choice. In that form this
    judge picked whichever set was shown first on 5 of 8 questions. Forcing
    the two per-set analyses out before the verdict makes the decision follow
    the evidence instead of the position.
    """

    analysis_a: str = Field(description="What set A covers and what it is missing for this question; cite excerpt numbers")
    analysis_b: str = Field(description="What set B covers and what it is missing for this question; cite excerpt numbers")
    winner: Literal["A", "B", "tie"]
    reason: str = Field(description="One sentence naming the concrete difference that decided it")


def get_index(name: str):
    client = Pinecone(api_key=settings.pinecone_api_key, host=settings.pinecone_host)
    described = client.describe_index(name)
    return client.Index(host=_resolve_index_host(described.host))


def search(index, company: str, query: str, top_k: int) -> list[str]:
    """Excerpt texts only.

    Deliberately not the scores, pages, or the section metadata the new index
    carries: any of those would tell the judge which side is which.
    """
    results = index.query(
        vector=list(_embed_query(query)),
        top_k=top_k,
        namespace="__default__",
        filter={"title": {"$eq": VECTOR_TITLE_BY_COMPANY[company]}},
        include_metadata=True,
    )
    return [match.metadata.get("text", "") for match in results.matches]


def _format(excerpts: list[str]) -> str:
    if not excerpts:
        return "(no excerpts retrieved)"
    return "\n\n".join(f"[{i}] {text}" for i, text in enumerate(excerpts, 1))


def judge_once(llm, question: str, set_a: list[str], set_b: list[str]) -> Verdict:
    return llm.invoke(
        [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    f"=== SET A ===\n{_format(set_a)}\n\n"
                    f"=== SET B ===\n{_format(set_b)}"
                ),
            },
        ]
    )


def compare(llm, question: str, excerpts_a: list[str], excerpts_b: list[str]) -> tuple[str, str]:
    """Returns (winner in {"a", "b", "tie"}, reason).

    Judged in both orders; a side wins only by being picked in both. When the
    two runs disagree the judge is following position, not content, so the
    pair is scored a tie and the raw verdicts are reported.
    """
    first = judge_once(llm, question, excerpts_a, excerpts_b)   # A=a, B=b
    second = judge_once(llm, question, excerpts_b, excerpts_a)  # A=b, B=a

    picks_a = (first.winner == "A", second.winner == "B")
    picks_b = (first.winner == "B", second.winner == "A")

    if all(picks_a):
        return "a", first.reason
    if all(picks_b):
        return "b", first.reason
    if first.winner == "tie" and second.winner == "tie":
        return "tie", first.reason
    return "tie", f"position-dependent ({first.winner}/{second.winner}) -- {first.reason}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-a", default="tenk-filings", help="baseline index")
    parser.add_argument("--index-b", default="tenk-filings-v2", help="candidate index")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--model", default="gpt-4o", help="judge model (not the app's chat model)")
    parser.add_argument("--dry-run", action="store_true", help="show retrieval only, no judging")
    args = parser.parse_args()

    index_a = get_index(args.index_a)
    index_b = get_index(args.index_b)

    print(f"A = {args.index_a}\nB = {args.index_b}\ntop_k = {args.top_k}\n")

    if args.dry_run:
        for company, question in QUESTIONS:
            print(f"\n{'=' * 78}\n{company}: {question}\n{'=' * 78}")
            for label, index in (("A " + args.index_a, index_a), ("B " + args.index_b, index_b)):
                print(f"\n--- {label} ---")
                for i, text in enumerate(search(index, company, question, args.top_k), 1):
                    print(f"{i}. {text[:180]!r}")
        return

    llm = ChatOpenAI(
        api_key=settings.openai_api_key, model=args.model, temperature=0
    ).with_structured_output(Verdict)

    tally: Counter[str] = Counter()
    rows = []
    for company, question in QUESTIONS:
        excerpts_a = search(index_a, company, question, args.top_k)
        excerpts_b = search(index_b, company, question, args.top_k)
        winner, reason = compare(llm, question, excerpts_a, excerpts_b)
        tally[winner] += 1
        rows.append((company, question, winner, reason))

        label = {"a": args.index_a, "b": args.index_b, "tie": "tie"}[winner]
        print(f"{company:7s} {question[:44]:44s} -> {label}")
        print(f"        {reason}")

    print(f"\n{'-' * 78}")
    print(f"{args.index_a}: {tally['a']}   {args.index_b}: {tally['b']}   tie: {tally['tie']}"
          f"   (of {len(QUESTIONS)})")


if __name__ == "__main__":
    main()
