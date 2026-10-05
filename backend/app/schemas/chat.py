from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.chat import MessageRole


class Citation(BaseModel):
    """A source passage backing an answer. `index` matches the [n] marker in the answer."""

    index: int
    chunk_id: str
    document_id: str
    filename: str
    page: int
    chunk_index: int
    text: str
    score: float


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None
    document_ids: list[uuid.UUID] | None = Field(
        default=None, description="Restrict retrieval to these documents (all ready docs if empty)."
    )
    top_k: int | None = Field(default=None, ge=1, le=20)

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[Citation] = []
    created_at: datetime


class SessionSummary(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class SessionDetail(SessionSummary):
    messages: list[MessageOut]


class HealthResponse(BaseModel):
    status: str
    version: str
    database: bool
    vector_store: bool
    llm_provider: str
    llm_configured: bool
    embedding_model: str
