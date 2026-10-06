"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REFUSAL_MESSAGE = "I couldn't find this in your documents."


class Settings(BaseSettings):
    """All runtime configuration. Every field maps to an UPPER_CASE env variable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -----------------------------------------------------------
    app_name: str = "DocuMind"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- Storage -----------------------------------------------------------
    database_url: str = "postgresql+psycopg://documind:documind@localhost:5432/documind"
    chroma_persist_dir: Path = Path("./data/chroma")
    chroma_collection: str = "documind_chunks"
    upload_dir: Path = Path("./data/uploads")
    max_upload_mb: int = Field(default=20, gt=0, le=200)
    # Hard cap on a whole upload request, enforced while the body streams in.
    max_request_mb: int = Field(default=60, gt=0, le=2000)
    max_files_per_upload: int = Field(default=10, ge=1, le=100)
    max_documents_per_workspace: int = Field(default=25, ge=1)

    # --- Embeddings --------------------------------------------------------
    # "onnx" runs the model with ONNX Runtime (small, no PyTorch); "sentence-transformers"
    # needs `pip install sentence-transformers` and supports GPUs via EMBEDDING_DEVICE.
    embedding_backend: Literal["onnx", "sentence-transformers"] = "onnx"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_batch_size: int = Field(default=32, gt=0)
    # ONNX Runtime threads; 0 = one per CPU core.
    embedding_threads: int = Field(default=0, ge=0)

    # --- Chunking & retrieval ---------------------------------------------
    chunk_size: int = Field(default=800, ge=100, le=8000)
    chunk_overlap: int = Field(default=150, ge=0)
    retrieval_top_k: int = Field(default=5, ge=1, le=50)
    retrieval_min_score: float = Field(default=0.3, ge=-1.0, le=1.0)
    history_turns: int = Field(default=3, ge=0, le=20)
    query_rewrite_enabled: bool = True

    # --- LLM ---------------------------------------------------------------
    llm_provider: Literal["gemini", "ollama"] = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"
    # Comma-separated models tried in order when the primary one is overloaded.
    gemini_fallback_models: str = "gemini-flash-lite-latest"
    gemini_thinking_budget: int | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(default=1024, gt=0)
    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    # --- API ---------------------------------------------------------------
    cors_origins: str = "http://localhost:3000"
    # Optional regex for extra allowed origins, e.g. Vercel preview URLs.
    cors_origin_regex: str | None = None
    chat_rate_limit_per_minute: int = Field(default=20, ge=0)
    upload_rate_limit_per_minute: int = Field(default=10, ge=0)
    # Number of reverse proxies in front of the API whose X-Forwarded-For entries
    # can be trusted. 0 = ignore the header (it can be forged by any client).
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    @field_validator("gemini_api_key", "gemini_thinking_budget", "cors_origin_regex", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        # `GEMINI_API_KEY=` in a .env file should mean "not set", not "empty key".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS is a comma-separated list (e.g. "http://a.com,http://b.com")."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def gemini_fallback_model_list(self) -> list[str]:
        return [m.strip() for m in self.gemini_fallback_models.split(",") if m.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_request_bytes(self) -> int:
        return self.max_request_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
