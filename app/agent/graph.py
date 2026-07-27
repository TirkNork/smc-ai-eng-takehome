"""Wiring: classify -> fetch_data -> check_grounding -> synthesize | refuse,
with a short circuit straight to converse for messages that ask for no data."""
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import check_grounding, converse, fetch_data, refuse_answer, synthesize_answer
from app.agent.router import classify_question
from app.agent.state import GraphState
from app.config import configure_tracing


def build_graph():
    # Must run before the graph executes so LangSmith picks up the env vars.
    configure_tracing()

    graph = StateGraph(GraphState)
    graph.add_node("classify", classify_question)
    graph.add_node("fetch_data", fetch_data)
    graph.add_node("check_grounding", check_grounding)
    graph.add_node("synthesize", synthesize_answer)
    graph.add_node("refuse", refuse_answer)
    graph.add_node("converse", converse)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        lambda state: "converse" if state.get("kind") == "general" else "fetch_data",
        {"converse": "converse", "fetch_data": "fetch_data"},
    )
    graph.add_edge("converse", END)
    graph.add_edge("fetch_data", "check_grounding")
    graph.add_conditional_edges(
        "check_grounding",
        lambda state: "synthesize" if state["grounded"] else "refuse",
        {"synthesize": "synthesize", "refuse": "refuse"},
    )
    graph.add_edge("synthesize", END)
    graph.add_edge("refuse", END)

    return graph.compile()
