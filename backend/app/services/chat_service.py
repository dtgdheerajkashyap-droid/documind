"""Chat orchestration: rewrite -> retrieve -> grounding gate -> generate -> cite -> persist."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anyio
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import REFUSAL_MESSAGE, Settings
from app.core.errors import AppError, NotFoundError
from app.db.session import session_scope
from app.models.chat import MessageRole
from app.providers.llm.base import LLMProvider
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.chat import ChatRequest, Citation
from app.services.prompts import (
    ANSWER_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    build_answer_prompt,
    build_rewrite_prompt,
    cited_indices,
    clean_rewritten_query,
    is_refusal,
)
from app.services.retrieval import RetrievedChunk, Retriever

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChatEvent:
    """One Server-Sent Event: `event` is the SSE event name, `data` its JSON payload."""

    event: str
    data: dict[str, Any] = field(default_factory=dict)


def build_citations(answer: str, chunks: list[RetrievedChunk]) -> list[Citation]:
    """Citations for the sources the answer references.

    `index` keeps the source's number from the prompt so it matches the [n]
    markers in the answer text. If the model cited nothing, every retrieved
    source is returned so the user can still verify the answer.
    """
    numbered = list(enumerate(chunks, 1))
    cited = set(cited_indices(answer, len(chunks)))
    selected = [(i, c) for i, c in numbered if i in cited] if cited else numbered
    return [
        Citation(
            index=i,
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            filename=c.filename,
            page=c.page,
            chunk_index=c.chunk_index,
            text=c.text,
            score=c.score,
        )
        for i, c in selected
    ]


class ChatService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        retriever: Retriever,
        llm: LLMProvider,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.retriever = retriever
        self.llm = llm

    def validate(self, request: ChatRequest, workspace_id: uuid.UUID) -> None:
        """Checks that must fail *before* the stream starts (so they return a JSON error)."""
        self.llm.ensure_configured()
        if request.session_id is not None:
            with session_scope(self.session_factory) as session:
                repo = ChatRepository(session)
                if repo.get_session(request.session_id, workspace_id) is None:
                    raise NotFoundError("Chat session not found.")

    async def rewrite_query(self, question: str, history: list[tuple[str, str]]) -> str:
        """Turn a follow-up ("what about its price?") into a standalone query."""
        if not history or not self.settings.query_rewrite_enabled:
            return question
        try:
            raw = await self.llm.generate(
                build_rewrite_prompt(question, history), system=REWRITE_SYSTEM_PROMPT
            )
        except AppError:
            logger.warning("Query rewrite failed; using the original question")
            return question
        return clean_rewritten_query(raw, fallback=question)

    async def stream(
        self, request: ChatRequest, workspace_id: uuid.UUID
    ) -> AsyncIterator[ChatEvent]:
        started = time.perf_counter()
        try:
            session_id, history = self._open_session(request, workspace_id)
            standalone = await self.rewrite_query(request.question, history)
            with session_scope(self.session_factory) as session:
                ChatRepository(session).add_message(
                    session_id,
                    MessageRole.USER,
                    request.question,
                    rewritten_query=(standalone if standalone != request.question else None),
                )
            yield ChatEvent("meta", {"session_id": str(session_id), "standalone_query": standalone})

            chunks = await self._retrieve(standalone, request, workspace_id)
            best = max((c.score for c in chunks), default=None)
            # Answer if a passage is semantically close enough, or names exactly what was
            # asked for ("Program 1") even though its embedding is not close (e.g. code).
            grounded = any(
                c.score >= self.settings.retrieval_min_score or c.keyword_match for c in chunks
            )

            if not grounded:
                answer, citations = REFUSAL_MESSAGE, []
                yield ChatEvent("token", {"text": answer})
            else:
                parts: list[str] = []
                prompt = build_answer_prompt(standalone, chunks)
                async for text in self.llm.stream(prompt, system=ANSWER_SYSTEM_PROMPT):
                    parts.append(text)
                    yield ChatEvent("token", {"text": text})
                answer = "".join(parts).strip()
                if not answer or is_refusal(answer):
                    answer, citations = REFUSAL_MESSAGE, []
                else:
                    citations = build_citations(answer, chunks)

            refused = not citations
            with session_scope(self.session_factory) as session:
                message = ChatRepository(session).add_message(
                    session_id,
                    MessageRole.ASSISTANT,
                    answer,
                    citations=[c.model_dump() for c in citations],
                )
                message_id = message.id

            yield ChatEvent("citations", {"citations": [c.model_dump() for c in citations]})
            yield ChatEvent(
                "done",
                {
                    "message_id": str(message_id),
                    "session_id": str(session_id),
                    "answer": answer,
                    "refused": refused,
                },
            )
            logger.info(
                "Chat answered",
                extra={
                    "session_id": str(session_id),
                    "retrieved": len(chunks),
                    "best_score": best,
                    "refused": refused,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
        except AppError as exc:
            logger.warning("Chat failed", extra={"code": exc.code, "error": exc.message})
            yield ChatEvent("error", {"code": exc.code, "message": exc.message})
        except Exception:
            logger.exception("Chat failed unexpectedly")
            yield ChatEvent(
                "error", {"code": "internal_error", "message": "An unexpected error occurred."}
            )

    def _open_session(
        self, request: ChatRequest, workspace_id: uuid.UUID
    ) -> tuple[uuid.UUID, list[tuple[str, str]]]:
        """Load (or create) the chat session and the recent turns used for query rewriting."""
        with session_scope(self.session_factory) as session:
            repo = ChatRepository(session)
            if request.session_id is None:
                title = (
                    request.question
                    if len(request.question) <= 80
                    else request.question[:77] + "..."
                )
                return repo.create_session(title, workspace_id).id, []
            chat = repo.get_session(request.session_id, workspace_id)
            if chat is None:
                raise NotFoundError("Chat session not found.")
            recent = repo.recent_messages(chat.id, limit=self.settings.history_turns * 2)
            return chat.id, [(m.role.value, m.content) for m in recent]

    async def _retrieve(
        self, query: str, request: ChatRequest, workspace_id: uuid.UUID
    ) -> list[RetrievedChunk]:
        document_ids: list[str] | None = None
        if request.document_ids:
            with session_scope(self.session_factory) as session:
                ready = DocumentRepository(session).ready_ids(workspace_id, request.document_ids)
            if not ready:
                return []
            document_ids = [str(d) for d in ready]
        top_k = request.top_k or self.settings.retrieval_top_k
        return await anyio.to_thread.run_sync(
            lambda: self.retriever.retrieve(
                query, top_k=top_k, document_ids=document_ids, workspace_id=str(workspace_id)
            )
        )
