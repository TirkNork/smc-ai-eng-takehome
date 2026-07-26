"""Sign-in gate for the Streamlit app.

The token lives in st.session_state, which is per browser session and held in
the server process -- so a page refresh signs the user out. A cookie would
survive that, but Streamlit has no first-class cookie API and a third-party
component is not worth it here.
"""
import streamlit as st

import api_client


def _sign_in(username: str, password: str) -> None:
    """Stores the token on success; renders the failure and returns otherwise."""
    if not username or not password:
        st.error("Enter a username and password.")
        return
    try:
        st.session_state.token = api_client.login(username, password)
        st.session_state.username = username
    except api_client.AuthError as exc:
        st.error(str(exc))
        return
    except api_client.BackendError as exc:
        st.error(str(exc))
        return
    st.rerun()


def _login_tab() -> None:
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", use_container_width=True):
            _sign_in(username, password)


def _register_tab() -> None:
    with st.form("register"):
        username = st.text_input("Username", help="Letters, numbers, . _ - (3-32 characters)")
        password = st.text_input("Password", type="password", help="At least 8-32 characters")
        if st.form_submit_button("Create account", use_container_width=True):
            if not username or not password:
                st.error("Enter a username and password.")
                return
            try:
                api_client.register(username, password)
            except (api_client.AuthError, api_client.BackendError) as exc:
                st.error(str(exc))
                return
            # Straight in, rather than making them retype what they just typed.
            _sign_in(username, password)


def require_login() -> str:
    """The access token, or renders the gate and halts the script.

    st.stop() is what keeps this honest: nothing below the call site runs until
    a token exists, so no page can forget to check.
    """
    if st.session_state.get("token"):
        return st.session_state.token

    st.title("📊 Financial Q&A")
    st.caption("Sign in to ask questions.")
    login, register = st.tabs(["Sign in", "Create account"])
    with login:
        _login_tab()
    with register:
        _register_tab()
    st.stop()


def sign_out() -> None:
    """Client-side only. The token stays valid until it expires -- revoking it
    server-side would mean a token blacklist, which needs a store this project
    does not have.
    """
    st.session_state.pop("token", None)
    st.session_state.pop("username", None)
    st.session_state.messages = []
