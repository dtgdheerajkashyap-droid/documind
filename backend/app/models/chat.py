"""Chat session and message tables."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow

# JSONB on Postgres, plain JSON elsewhere (SQLite in tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, index=True
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            name="message_role",
            native_enum=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    content: Mapped[str] = mapped_column(Text)
    # For assistant messages: the citations shown to the user.
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    # For user messages: the standalone query actually used for retrieval.
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
