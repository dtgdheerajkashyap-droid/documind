"""Reject oversized request bodies while they stream in.

FastAPI parses multipart uploads (spooling them to disk) *before* the route runs,
so a per-file size check in the route alone would still let a client upload
gigabytes. This middleware enforces a hard cap on the whole request body:
immediately from Content-Length when present, and by counting bytes as they
arrive otherwise (e.g. chunked transfer encoding).
"""

from __future__ import annotations

import json

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_body


class BodySizeLimitMiddleware:
    def __init__(
        self, app: ASGIApp, max_bytes: int, path_prefixes: tuple[str, ...] = ("/api/",)
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.path_prefixes = path_prefixes

    def _message(self) -> str:
        return f"Request body too large (limit {self.max_bytes // (1024 * 1024)} MB)."

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in ("POST", "PUT", "PATCH")
            or not scope["path"].startswith(self.path_prefixes)
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > self.max_bytes
        ):
            await self._reject(send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Handled by the app's HTTPException handler -> JSON 413.
                    raise HTTPException(status_code=413, detail=self._message())
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps(error_body("payload_too_large", self._message())).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
