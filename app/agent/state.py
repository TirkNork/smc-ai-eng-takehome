from typing import Literal, Optional, TypedDict


class GraphState(TypedDict, total=False):
    question: str
    companies: list[str]
    route: Literal["sql", "vector", "hybrid", "unsupported"]
    retrieval_query: str
    sql_results: list[dict]
    vector_results: list[dict]
    grounded: bool
    missing_reason: Optional[str]
    error: Optional[str]
    answer: str
