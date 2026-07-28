"""Typed app settings, loaded once from .env. Add fields here as new parts
of the app (auth, FastAPI) need env vars -- don't scatter os.environ.get()
calls through the codebase.
"""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/findb"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    db_pool_timeout: float = 5.0
    db_connect_timeout: int = 5
    
    pinecone_host: str = "http://localhost:5080"
    pinecone_api_key: str = "pclocal"
    pinecone_index: str = "tenk-filings"
    
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dim: int = 512
    
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # LangSmith tracing. Optional -- the app runs normally without a key.
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "smc-finance-chatbot"
    langsmith_endpoint: str = "https://api.smith.langchain.com"


settings = Settings()


def configure_tracing() -> bool:
    """Export LangSmith settings into os.environ.

    Required because LangChain/LangGraph read tracing config from os.environ
    directly, while pydantic-settings only parses .env into this object --
    it does not populate os.environ. Without this, LANGSMITH_* values in .env
    are silently ignored and no traces are ever sent.

    Returns whether tracing was enabled.
    """
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        os.environ["LANGSMITH_TRACING"] = "false"
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    return True
