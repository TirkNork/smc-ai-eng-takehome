"""Streamlit chat UI.

Run: uv run streamlit run frontend/app.py

Deliberately surfaces the grounding metadata the API returns rather than only
the prose: which sources were used, which companies had no data, and which
filing pages backed the answer. The point of this project is that an answer
is never invented, and that is only believable if it is visible.
"""
import streamlit as st

import api_client

ROUTE_LABEL = {
    "sql": "📊 Financial database",
    "vector": "📄 10-K filings",
    "hybrid": "📊 Financial database + 📄 10-K filings",
    "unsupported": "🚫 Outside available data",
}

EXAMPLES = [
    "สรุป net income ปี 2022-2025 ของบริษัท Apple",
    "เปรียบเทียบโครงสร้างรายได้และกลยุทธ์ทางธุรกิจของ Google และ Facebook ปี 2025",
    "จากรายได้ของ Microsoft, Apple, Google, Facebook ปี 2024-2025 บริษัทใดเติบโตสูงสุด และอะไรเป็นปัจจัยหลัก",
]

st.set_page_config(page_title="Financial Q&A", page_icon="📊", layout="centered")


def render_sources(meta: dict) -> None:
    """Grounding panel shown under each answer."""
    if not meta.get("grounded"):
        # Nothing was answered, so there is no coverage to qualify -- the
        # refusal text already says why. Calling that "partial coverage"
        # would describe a full refusal as a partial answer.
        return

    if meta.get("missing_reason"):
        st.warning(f"Partial coverage — {meta['missing_reason']}", icon="⚠️")

    bits = [ROUTE_LABEL.get(meta.get("route"), meta.get("route", ""))]
    if meta.get("companies"):
        bits.append("Companies: " + ", ".join(meta["companies"]))

    citations = meta.get("citations") or []
    if citations:
        pages: dict[str, list[int]] = {}
        for c in citations:
            pages.setdefault(c["company"], []).append(c["page"])
        bits.append(
            "Cited pages: "
            + " · ".join(f"{co} p.{', '.join(map(str, pg))}" for co, pg in pages.items())
        )

    with st.expander("Sources", expanded=False):
        for bit in bits:
            st.caption(bit)


# --- sidebar -----------------------------------------------------------------
with st.sidebar:
    st.subheader("Backend")
    status = api_client.health()
    if status is None:
        st.error(f"Unreachable\n\n`{api_client.BACKEND_URL}`")
    else:
        (st.success if status["status"] == "ok" else st.warning)(status["status"])
        for name, result in status["checks"].items():
            st.caption(f"{name}: {result}")

    st.divider()
    st.caption(
        "Answers come only from an income-statement database (~48 US companies, "
        "2022-2025) and four FY2025 10-K filings (Alphabet, Amazon, Apple, Meta). "
        "Anything outside that is refused rather than guessed."
    )
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

# --- main --------------------------------------------------------------------
st.title("📊 Financial Q&A")

if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    st.caption("Try one of these:")
    for i, example in enumerate(EXAMPLES):
        if st.button(example, key=f"ex{i}", use_container_width=True):
            st.session_state.pending = example
            st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("meta"):
            render_sources(message["meta"])

question = st.chat_input("Ask about a company's financials or strategy…")
if not question and "pending" in st.session_state:
    question = st.session_state.pop("pending")

if question:
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Retrieving and checking sources…"):
            try:
                result = api_client.ask(question, history)
            except api_client.BackendError as exc:
                st.error(str(exc))
                # Not stored in history: it is a transport failure, not an
                # answer, and should not be replayed on the next rerun.
                st.stop()

        st.markdown(result["answer"])
        render_sources(result)

    st.session_state.messages.append(
        {"role": "assistant", "content": result["answer"], "meta": result}
    )
    # Redraw so the example buttons (rendered earlier this run, while the
    # history was still empty) disappear now that a conversation exists.
    # Cheap: the answer is already in session_state, so nothing is re-fetched.
    st.rerun()
