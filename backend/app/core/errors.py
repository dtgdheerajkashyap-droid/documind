"""Domain exceptions and handlers that render every error as consistent JSON.

Every error response has the shape::

    {"error": {"code": "not_found", "message": "Document not found", "details": null}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that map cleanly to an HTTP response."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"

    def __init__(
        self, message: str, *, details: Any = None, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class InvalidUploadError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_upload"


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class LLMNotConfiguredError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "llm_not_configured"


class LLMProviderError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "llm_error"


class IngestionError(Exception):
    """Raised when a document cannot be ingested (e.g. no extractable text)."""


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(err.get("loc", [])), "message": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "Request validation failed", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", extra={"path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal_error", "An unexpected error occurred."),
        )
