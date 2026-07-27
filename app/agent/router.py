"""Node: classify the message -- general chat or a data question, and if the
latter, which companies, years and source(s) it needs.

LLM-based (structured output) rather than keywords: "what's driving X's growth"
needs the filings and matches no fixed keyword list.

The real company list is passed in so a mention maps onto the exact string the
SQL table uses -- names there are inconsistently formatted ("AmericanExpress"
has no space, "Morgan Stanley" does) and a naive extraction matches neither.
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
    kind: Literal["general", "data"] = Field(
        description="Whether the message asks for company data, or is about this assistant / the conversation / merely social"
    )
    standalone_question: str = Field(
        description="The question rewritten to stand alone, in its original language"
    )
    route: Literal["sql", "vector", "hybrid", "unsupported"] = "unsupported"
    companies: list[str] = Field(default_factory=list, description="Company names, mapped to the known list where applicable")
    years: list[int] = Field(default_factory=list, description="Fiscal years explicitly asked for")
    retrieval_query: str = Field(default="", description="English query describing what to find in the 10-K filings")


_llm = ChatOpenAI(
    api_key=settings.openai_api_key, model=settings.openai_chat_model, temperature=0
).with_structured_output(Classification)


def classify_question(state: GraphState) -> dict:
    # Captured as `error` rather than raised, matching fetch_data: a database
    try:
        known_companies = list_known_companies()
    except Exception as exc:
        return {
            "kind": "data",
            "route": "unsupported",
            "companies": [],
            "error": f"could not reach the financial database ({type(exc).__name__})",
        }

    # History is passed as real prior turns, so the model resolves a follow-up
    # the way it reads one. It reaches this node only -- downstream nodes see
    # the rewritten question, never the transcript, so an earlier answer can't
    # become a source of facts for this one.
    result: Classification = _llm.invoke(
        [
            {"role": "system", "content": classify_system_prompt(known_companies)},
            *(state.get("history") or []),
            {"role": "user", "content": state["question"]},
        ]
    )

    standalone_question = result.standalone_question.strip() or state["question"]

    if result.kind == "general":
        return {
            "kind": "general",
            "standalone_question": standalone_question,
            "companies": [],
            "years": [],
            "route": "unsupported",
            "retrieval_query": "",
        }

    # Deterministic safety net over the LLM's own mapping, then narrowed to the
    # companies this question actually names -- with history in the prompt the
    # classifier keeps returning earlier turns' companies, whose data would
    # otherwise be retrieved for a question that never asked about them.
    companies = sorted({normalize_company(c) for c in result.companies})
    companies = mentioned_in(companies, standalone_question)

    # "unsupported" with companies present is not a contradiction: the subject
    # matter is outside both sources (e.g. "Apple's share price"). Deciding it
    # here avoids a pointless DB read, embedding call and synthesis.
    route = result.route if companies else "unsupported"

    return {
        "kind": "data",
        "standalone_question": standalone_question,
        "companies": companies,
        "years": sorted(set(result.years)),
        "route": route,
        "retrieval_query": result.retrieval_query.strip() or standalone_question,
    }
