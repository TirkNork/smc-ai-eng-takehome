"""fetch_data, check_grounding, synthesize, refuse -- the rest of the graph
besides classify (router.py)."""
import json

from langchain_openai import ChatOpenAI

from app.agent.prompts import (
    REFUSE_SYSTEM_PROMPT,
    SYNTHESIZE_SYSTEM_PROMPT,
    converse_system_prompt,
    partial_coverage_note,
    sql_context_header,
    vector_context_header,
)
from app.agent.state import GraphState
from app.config import settings
from app.data_access.companies import COMPANY_BY_VECTOR_TITLE
from app.data_access.financial_data import coverage_summary, list_known_companies, query_financials
from app.data_access.vector import search_filings

_llm = ChatOpenAI(api_key=settings.openai_api_key, model=settings.openai_chat_model, temperature=0)


def _question(state: GraphState) -> str:
    """What this turn is actually asking. classify rewrites a follow-up into a
    self-contained question; falls back to the raw text on a first turn or if
    classify short-circuited on a database error."""
    return state.get("standalone_question") or state["question"]


def _question_block(state: GraphState) -> str:
    """Both wordings, for the nodes that write the reply.

    The rewrite is what the question MEANS, but it is not reliably in the
    user's language ("why?" came back rewritten in Thai). So the user's own
    wording is given alongside it as the language anchor -- the reply must
    match how they wrote it.
    """
    question = state["question"]
    standalone = _question(state)
    if standalone == question:
        return f"Question: {question}"
    return (
        f"Question, as the user wrote it -- REPLY IN THIS LANGUAGE: {question}\n"
        f"The same question resolved against the conversation, this is what to answer: {standalone}"
    )


def fetch_data(state: GraphState) -> dict:
    """Retrieval failures are captured as `error` rather than raised, so an
    outage is reported honestly as a service problem instead of crashing --
    and, critically, never as "this data does not exist"."""
    updates: dict = {}
    route = state["route"]

    if route in ("sql", "hybrid"):
        try:
            updates["sql_results"] = query_financials(state["companies"])
        except Exception as exc:
            updates["error"] = f"could not reach the financial database ({type(exc).__name__})"
            return updates

    if route in ("vector", "hybrid"):
        results = []
        try:
            for company in state["companies"]:
                results.extend(search_filings(company, state.get("retrieval_query") or _question(state)))
        except Exception as exc:
            updates["error"] = f"could not reach the filings search service ({type(exc).__name__})"
            return updates
        updates["vector_results"] = results

    return updates


def check_grounding(state: GraphState) -> dict:
    """The no-hallucination gate.

    Coverage is derived from what was ACTUALLY returned, per requested
    company, uniformly across every route -- not from a static coverage
    constant, and not only for the hybrid route. A company the user asked
    about that produced no data is always named in missing_reason so the
    answer discloses it instead of silently dropping it.
    """
    if state.get("error"):
        return {"grounded": False, "missing_reason": state["error"]}

    route = state["route"]
    companies = state.get("companies") or []
    sql_results = state.get("sql_results") or []
    vector_results = state.get("vector_results") or []

    if route == "unsupported" or not companies:
        reason = (
            "no company identified in the question"
            if not companies
            else "the question asks about something outside this assistant's two data "
            "sources (income-statement figures and 10-K filing text)"
        )
        return {"grounded": False, "missing_reason": reason}

    notes = []

    if route in ("sql", "hybrid"):
        returned = {row["company"] for row in sql_results}
        missing = [c for c in companies if c not in returned]
        if missing:
            notes.append(f"no financial data for: {', '.join(missing)}")

        # A company matching is not the same as the asked-for year being on
        # file: rows come back for every year we hold, so without this a
        # question about 2019 would be answered from the 2023-2025 rows.
        years = state.get("years") or []
        if years and sql_results:
            on_file = {row["year"] for row in sql_results}
            missing_years = [y for y in years if y not in on_file]
            if missing_years:
                note = f"no financial data for fiscal year(s): {', '.join(str(y) for y in missing_years)}"
                if len(missing_years) == len(years) and route == "sql":
                    return {"grounded": False, "missing_reason": note}
                notes.append(note)

    if route in ("vector", "hybrid"):
        returned = {
            COMPANY_BY_VECTOR_TITLE[chunk["title"]]
            for chunk in vector_results
            if chunk["title"] in COMPANY_BY_VECTOR_TITLE
        }
        missing = [c for c in companies if c not in returned]
        if missing:
            notes.append(f"no 10-K filing text for: {', '.join(missing)}")

    missing_reason = "; ".join(notes) if notes else None

    # Refuse only when nothing at all came back; partial coverage still gets
    # answered, with the gap disclosed.
    if not sql_results and not vector_results:
        return {"grounded": False, "missing_reason": missing_reason or "no data available"}

    return {"grounded": True, "missing_reason": missing_reason}


def synthesize_answer(state: GraphState) -> dict:
    context_parts = []
    sql_results = state.get("sql_results") or []
    vector_results = state.get("vector_results") or []

    if sql_results:
        sql_companies = sorted({row["company"] for row in sql_results})
        context_parts.append(
            sql_context_header(sql_companies) + "\n" + json.dumps(sql_results, indent=2)
        )

    if vector_results:
        vector_companies = sorted(
            {COMPANY_BY_VECTOR_TITLE.get(c["title"], c["title"]) for c in vector_results}
        )
        chunks = "\n\n".join(f"[{c['title']} p.{c['page']}] {c['text']}" for c in vector_results)
        context_parts.append(vector_context_header(vector_companies) + "\n" + chunks)

    if state.get("missing_reason"):
        context_parts.append(partial_coverage_note(state["missing_reason"]))

    context = "\n\n---\n\n".join(context_parts) if context_parts else "(no data available)"

    response = _llm.invoke(
        [
            {"role": "system", "content": SYNTHESIZE_SYSTEM_PROMPT},
            {"role": "user", "content": f"{_question_block(state)}\n\nAvailable data:\n{context}"},
        ]
    )
    return {"answer": response.content}


def converse(state: GraphState) -> dict:
    """Messages that ask for no company data -- about the assistant, about the
    conversation, or social.

    `grounded` is True because the reply asserts nothing that could be
    ungrounded, not because a source backed it. This is the only node besides
    classify that sees the transcript, so its prompt forbids restating a figure
    from it -- every number the user is shown comes from a fresh retrieval.
    """
    try:
        coverage = coverage_summary()
        known_companies = list_known_companies()
    except Exception:
        # Describing our own scope is not worth failing a greeting over.
        coverage, known_companies = None, []

    response = _llm.invoke(
        [
            {"role": "system", "content": converse_system_prompt(coverage, known_companies)},
            *(state.get("history") or []),
            {"role": "user", "content": state["question"]},
        ]
    )
    return {"answer": response.content, "grounded": True, "missing_reason": None}


def refuse_answer(state: GraphState) -> dict:
    response = _llm.invoke(
        [
            {"role": "system", "content": REFUSE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{_question_block(state)}\n\nReason: {state.get('missing_reason') or 'unknown reason'}",
            },
        ]
    )
    return {"answer": response.content}
