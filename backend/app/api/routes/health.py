"""Liveness/readiness information."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import ContainerDep
from app.core.errors import LLMNotConfiguredError
from app.schemas.chat import HealthResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
def health(container: ContainerDep) -> HealthResponse:
    try:
        with container.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:
        logger.warning("Database health check failed", extra={"error": str(exc)})
        database_ok = False

    try:
        container.llm.ensure_configured()
        llm_configured = True
    except LLMNotConfiguredError:
        llm_configured = False

    vector_ok = container.vector_store.healthcheck()
    return HealthResponse(
        status="ok" if database_ok and vector_ok else "degraded",
        version=__version__,
        database=database_ok,
        vector_store=vector_ok,
        llm_provider=container.llm.name,
        llm_configured=llm_configured,
        embedding_model=container.embedder.model_name,
    )
