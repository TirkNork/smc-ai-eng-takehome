"""Shared FastAPI dependencies.

Auth is not implemented yet. When it is, `get_current_user` belongs here and
routes gain `user = Depends(get_current_user)` -- no route logic changes.
"""
from fastapi import Request


def get_graph(request: Request):
    """The compiled LangGraph, built once at startup (see main.lifespan)."""
    return request.app.state.graph
