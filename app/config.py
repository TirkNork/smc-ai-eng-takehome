"""Typed app settings, loaded once from .env. Add fields here as new parts
of the app (auth, FastAPI, LangSmith) need env vars -- don't scatter
os.environ.get() calls through the codebase.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/findb"
    pinecone_host: str = "http://localhost:5080"
    pinecone_api_key: str = "pclocal"
    pinecone_index: str = "tenk-filings"
    openai_embedding_dim: int = 512


settings = Settings()
