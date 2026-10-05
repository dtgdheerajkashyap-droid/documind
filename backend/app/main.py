"""FastAPI application factory."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.api.routes import chat, documents, health, sessions
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import get_settings
from app.core.container import AppContainer, build_container
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware:
    """Pure-ASGI middleware (safe with streaming responses) that logs every request
    and propagates an X-Request-ID header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        request_id = headers.get(b"x-request-id", b"").decode() or uuid.uuid4().hex
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )


def _startup_tasks(container: AppContainer) -> None:
    """Load the embedding model, then recover from a previous crash/restart."""
    try:
        container.embedder.embed_query("warm-up")
    except Exception:
        logger.exception("Embedding model warm-up failed")
    container.ingestion_queue.recover()


def create_app(container: AppContainer | None = None) -> FastAPI:
    settings = container.settings if container else get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(app.state, "container", None) is None:
            app.state.container = build_container(settings)
        c: AppContainer = app.state.container
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "DocuMind started", extra={"llm": c.llm.name, "embedding_model": c.embedder.model_name}
        )
        # In the background, so the API is available immediately: warm up the embedding
        # model, re-queue interrupted uploads and rebuild vectors lost on restart.
        threading.Thread(target=_startup_tasks, args=(c,), daemon=True, name="startup").start()
        try:
            c.llm.ensure_configured()
        except Exception as exc:
            # Start anyway; the chat endpoint returns a clear error until this is fixed.
            logger.warning("LLM is not configured", extra={"error": str(exc)})
        yield
        c.ingestion_queue.shutdown()
        c.engine.dispose()

    app = FastAPI(
        title="DocuMind API",
        version=__version__,
        description="Retrieval-augmented question answering over your PDF documents.",
        lifespan=lifespan,
    )
    app.state.container = container

    # Order matters: the last middleware added is the outermost. The body limit sits
    # inside CORS so that its 413 responses still carry CORS headers.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    api = APIRouter(prefix="/api")
    for module in (health, documents, chat, sessions):
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
