"""Node: classify the question -- companies mentioned, which source(s) are
needed, and what to search the filings for.

LLM-based (structured output), not fixed keywords -- a keyword list can't
generalize to arbitrary phrasings ("what's driving X's growth" needs vector
reasoning with no keyword match against any fixed list); sql-vs-vector-vs
-hybrid is a semantic judgment, not a lexical one.

The model is given the real company list from financial_data so it maps a
mention onto the exact string the SQL table uses -- company names there are
inconsistently formatted ("AmericanExpress", "BankOfAmerica" have no spaces;
"Morgan Stanley", "Eli Lilly" do) and a naive extraction would silently fail
to match any of them.
"""
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agent.prompts import classify_system_prompt
from app.agent.state import GraphState
from app.config import settings
from app.data_access.companies import mentioned_in, normalize_company
from app.data_access.sql import list_known_companies


class Classification(BaseModel):
    # Declared first on purpose: structured output is generated field by field
    # in this order, so the model resolves the follow-up before deciding
    # companies and route -- and can then read those off a complete question.
    standalone_question: str = Field(
        description="The question rewritten to stand alone, in its original language"
    )
    companies: list[str] = Field(description="Company names, mapped to the known list where applicable")
    route: Literal["sql", "vector", "hybrid", "unsupported"]
    retrieval_query: str = Field(default="", description="English query describing what to find in the 10-K filings")


_llm = ChatOpenAI(
    api_key=settings.openai_api_key, model=settings.openai_chat_model, temperature=0
).with_structured_output(Classification)


def classify_question(state: GraphState) -> dict:
    # Captured as `error` rather than raised, matching fetch_data: a database
    # outage should reach the user as the same honest "temporarily
    # unavailable" reply wherever it happens, not as an HTTP error from this
    # node and a graceful message from the next one.
    try:
        known_companies = list_known_companies()
    except Exception as exc:
        return {
            "route": "unsupported",
            "companies": [],
            "error": f"could not reach the financial database ({type(exc).__name__})",
        }

    system_prompt = classify_system_prompt(known_companies)

    # History is passed as real prior turns, so the model resolves a follow-up
    # the way it reads one. It reaches this node only -- downstream nodes see
    # the rewritten question, never the transcript, so an earlier answer can't
    # become a source of facts for this one.
    result: Classification = _llm.invoke(
        [
            {"role": "system", "content": system_prompt},
            *(state.get("history") or []),
            {"role": "user", "content": state["question"]},
        ]
    )

    # Deterministic safety net on top of the LLM's own mapping -- cheap, and
    # catches the well-known Facebook/Meta, Alphabet/Google renamings even if
    # the model's output ever slipped.
    companies = sorted({normalize_company(c) for c in result.companies})

    # Narrowed to the companies this question actually names: with history in
    # the prompt the classifier keeps returning earlier turns' companies, which
    # would retrieve their data for a question that never asked about them.
    standalone_question = result.standalone_question.strip() or state["question"]
    companies = mentioned_in(companies, standalone_question)

    # "unsupported" with companies present is not a contradiction: it means the
    # subject matter is outside both sources (e.g. "Apple's share price").
    # Short-circuiting here avoids a pointless DB read, embedding call and
    # synthesis for a question no retrieval could ever answer.
    route = "unsupported" if not companies else result.route

    return {
        "standalone_question": standalone_question,
        "companies": companies,
        "route": route,
        "retrieval_query": result.retrieval_query.strip() or standalone_question,
    }
