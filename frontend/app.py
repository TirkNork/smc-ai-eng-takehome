"""Streamlit chat UI.

Run: uv run streamlit run frontend/app.py

Deliberately surfaces the grounding metadata the API returns rather than only
the prose: which sources were used, which companies had no data, and which
filing pages backed the answer. The point of this project is that an answer
is never invented, and that is only believable if it is visible.
"""
import streamlit as st

import api_client
import auth

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


# --- sidebar, before the gate ------------------------------------------------
# Rendered while signed out too, which is why /health needs no auth: "the stack
# is down" and "you are not signed in" must not look the same.
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

# Halts the script and shows the sign-in form when there is no token, so nothing
# below can run unauthenticated.
token = auth.require_login()

def _load_session(session_id: str | None) -> None:
    """Switches the active conversation, pulling its messages from the server
    -- session_state only ever holds what's currently on screen, never the
    source of truth."""
    st.session_state.session_id = session_id
    if session_id is None:
        st.session_state.messages = []
        return
    try:
        rows = api_client.get_session_messages(session_id, token)
    except (api_client.AuthError, api_client.BackendError) as exc:
        st.error(str(exc))
        st.session_state.session_id = None
        st.session_state.messages = []
        return
    st.session_state.messages = [
        {
            "role": row["role"],
            "content": row["content"],
            "meta": {
                "grounded": row["grounded"],
                "missing_reason": row["missing_reason"],
                "route": row["route"],
                "companies": row["companies"],
                "citations": row["citations"],
            },
        }
        for row in rows
    ]


# --- sidebar, signed in ------------------------------------------------------
with st.sidebar:
    st.divider()
    st.caption(f"Signed in as **{st.session_state.username}**")

    if st.button("➕ New chat", use_container_width=True):
        _load_session(None)
        st.rerun()

    try:
        past_sessions = api_client.list_sessions(token)
    except (api_client.AuthError, api_client.BackendError) as exc:
        past_sessions = []
        st.error(str(exc))

    for session in past_sessions:
        is_active = session["id"] == st.session_state.get("session_id")
        col1, col2 = st.columns([5, 1])
        with col1:
            label = ("**" + session["title"] + "**") if is_active else session["title"]
            if st.button(label, key=f"session-{session['id']}", use_container_width=True):
                _load_session(session["id"])
                st.rerun()
        with col2:
            if st.button("🗑", key=f"delete-{session['id']}"):
                try:
                    api_client.delete_session(session["id"], token)
                except (api_client.AuthError, api_client.BackendError) as exc:
                    st.error(str(exc))
                else:
                    if is_active:
                        _load_session(None)
                st.rerun()

    st.divider()
    if st.button("Sign out", use_container_width=True):
        auth.sign_out()
        st.rerun()

# --- main --------------------------------------------------------------------
st.title("📊 Financial Q&A")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None

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
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Retrieving and checking sources…"):
            try:
                result = api_client.ask(question, st.session_state.session_id, token)
            except api_client.AuthError as exc:
                # The token expired mid-conversation. Drop it so the next run
                # shows the sign-in form instead of failing every question.
                st.session_state.pop("token", None)
                st.warning(str(exc))
                st.stop()
            except api_client.BackendError as exc:
                st.error(str(exc))
                # Not stored in history: it is a transport failure, not an
                # answer, and should not be replayed on the next rerun.
                st.stop()

        st.markdown(result["answer"])
        render_sources(result)

    # The very first message in a conversation gets a session_id back that
    # didn't exist before this call -- store it so the next question continues
    # the same conversation instead of starting a new one each time.
    st.session_state.session_id = result["session_id"]

    st.session_state.messages.append(
        {"role": "assistant", "content": result["answer"], "meta": result}
    )
    # Redraw so the example buttons (rendered earlier this run, while the
    # history was still empty) disappear now that a conversation exists, and
    # so the sidebar's session list picks up the new/renamed conversation.
    st.rerun()
