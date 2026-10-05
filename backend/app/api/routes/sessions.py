"""Chat session history."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import DbDep
from app.core.errors import NotFoundError
from app.core.workspace import WorkspaceDep
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import MessageOut, SessionDetail, SessionSummary

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
def list_sessions(db: DbDep, workspace_id: WorkspaceDep) -> list[SessionSummary]:
    return [
        SessionSummary(
            id=chat.id,
            title=chat.title,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            message_count=count,
        )
        for chat, count in ChatRepository(db).list_sessions(workspace_id)
    ]


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: uuid.UUID, db: DbDep, workspace_id: WorkspaceDep) -> SessionDetail:
    chat = ChatRepository(db).get_session(session_id, workspace_id)
    if chat is None:
        raise NotFoundError("Chat session not found.")
    return SessionDetail(
        id=chat.id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        message_count=len(chat.messages),
        messages=[MessageOut.model_validate(m) for m in chat.messages],
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: uuid.UUID, db: DbDep, workspace_id: WorkspaceDep) -> Response:
    repo = ChatRepository(db)
    chat = repo.get_session(session_id, workspace_id)
    if chat is None:
        raise NotFoundError("Chat session not found.")
    repo.delete_session(chat)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
