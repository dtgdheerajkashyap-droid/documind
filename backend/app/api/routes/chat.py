"""Streaming chat endpoint (Server-Sent Events)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import ContainerDep
from app.core.rate_limit import client_key
from app.core.workspace import WorkspaceDep
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatEvent

router = APIRouter(prefix="/chat", tags=["chat"])


def format_sse(event: ChatEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


async def _sse(events: AsyncIterator[ChatEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield format_sse(event)


@router.post(
    "",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "SSE stream of `meta`, `token`, `citations`, `done` (or `error`) events.",
        }
    },
)
async def chat(
    payload: ChatRequest, request: Request, container: ContainerDep, workspace_id: WorkspaceDep
) -> StreamingResponse:
    """Answer a question from the uploaded documents, streaming the answer as SSE.

    Errors detected before streaming (missing API key, unknown session, rate limit)
    are returned as regular JSON error responses.
    """
    container.chat_rate_limiter.check(client_key(request, container.settings.trusted_proxy_hops))
    service = container.chat_service
    await anyio.to_thread.run_sync(service.validate, payload, workspace_id)
    return StreamingResponse(
        _sse(service.stream(payload, workspace_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
