"""Data access for chat sessions and messages."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.chat import ChatMessage, ChatSession, MessageRole


class ChatRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(self, title: str, workspace_id: uuid.UUID) -> ChatSession:
        chat = ChatSession(title=title[:200], workspace_id=workspace_id)
        self.session.add(chat)
        self.session.flush()
        return chat

    def get_session(
        self, session_id: uuid.UUID, workspace_id: uuid.UUID | None = None
    ) -> ChatSession | None:
        """Fetch a session; when `workspace_id` is given, other workspaces' sessions are hidden."""
        chat = self.session.get(ChatSession, session_id)
        if chat is None or (workspace_id is not None and chat.workspace_id != workspace_id):
            return None
        return chat

    def list_sessions(self, workspace_id: uuid.UUID) -> list[tuple[ChatSession, int]]:
        """The workspace's sessions, most recently active first, with their message counts."""
        counts = (
            select(ChatMessage.session_id, func.count(ChatMessage.id).label("n"))
            .group_by(ChatMessage.session_id)
            .subquery()
        )
        stmt = (
            select(ChatSession, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.session_id == ChatSession.id)
            .where(ChatSession.workspace_id == workspace_id)
            .order_by(ChatSession.updated_at.desc())
        )
        return [(row[0], int(row[1])) for row in self.session.execute(stmt).all()]

    def delete_session(self, chat: ChatSession) -> None:
        self.session.delete(chat)
        self.session.flush()

    def add_message(
        self,
        session_id: uuid.UUID,
        role: MessageRole,
        content: str,
        *,
        citations: list[dict[str, Any]] | None = None,
        rewritten_query: str | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            citations=citations or [],
            rewritten_query=rewritten_query,
        )
        self.session.add(message)
        chat = self.session.get(ChatSession, session_id)
        if chat is not None:
            chat.updated_at = utcnow()
        self.session.flush()
        return message

    def recent_messages(self, session_id: uuid.UUID, limit: int) -> Sequence[ChatMessage]:
        """The last `limit` messages of a session, in chronological order."""
        if limit <= 0:
            return []
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        return list(reversed(self.session.scalars(stmt).all()))
