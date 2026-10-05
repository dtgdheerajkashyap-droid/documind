"""Google Gemini provider (uses the official `google-genai` SDK).

Free-tier Gemini models are often briefly overloaded (HTTP 503) or rate limited
(HTTP 429). Requests are therefore retried with exponential backoff, and then
tried on each fallback model in order before giving up.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any, TypeVar

from app.core.errors import LLMNotConfiguredError, LLMProviderError
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")

MISSING_KEY_MESSAGE = (
    "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey, "
    "add GEMINI_API_KEY=<your key> to your .env file, and restart the backend."
)

TRANSIENT_STATUS_CODES = {429, 500, 503, 504}


def is_transient(exc: BaseException) -> bool:
    """Overload, rate limit and timeout errors are worth retrying; bad requests are not."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code in TRANSIENT_STATUS_CODES
    return (
        isinstance(exc, (TimeoutError, ConnectionError)) or "timeout" in type(exc).__name__.lower()
    )


def _describe(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if code == 429:
        return "Gemini rate limit reached. Please wait a moment and try again."
    if code in (500, 503, 504):
        return "Gemini is temporarily overloaded. Please try again in a moment."
    return f"Gemini request failed: {exc}"


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        fallback_models: Sequence[str] = (),
        temperature: float = 0.1,
        max_output_tokens: int = 1024,
        thinking_budget: int | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._models = [model, *(m for m in fallback_models if m and m != model)]
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._thinking_budget = thinking_budget
        self._timeout_ms = int(timeout_seconds * 1000)
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._client: Any = None

    @property
    def name(self) -> str:
        return f"gemini:{self._models[0]}"

    def ensure_configured(self) -> None:
        if not self._api_key:
            raise LLMNotConfiguredError(MISSING_KEY_MESSAGE)

    def _get_client(self) -> Any:
        self.ensure_configured()
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self._api_key, http_options=types.HttpOptions(timeout=self._timeout_ms)
            )
        return self._client

    def _config(self, system: str | None) -> Any:
        from google.genai import types

        kwargs: dict[str, Any] = {
            "temperature": self._temperature,
            "max_output_tokens": self._max_output_tokens,
        }
        if system:
            kwargs["system_instruction"] = system
        if self._thinking_budget is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=self._thinking_budget)
        return types.GenerateContentConfig(**kwargs)

    async def _with_resilience(self, call: Callable[[str], Awaitable[T]]) -> T:
        """Run `call(model)` with retries on transient errors, then on each fallback model."""
        last_exc: BaseException | None = None
        for model in self._models:
            for attempt in range(self._max_retries + 1):
                try:
                    return await call(model)
                except LLMNotConfiguredError:
                    raise
                except Exception as exc:  # the SDK raises a variety of error types
                    last_exc = exc
                    if not is_transient(exc):
                        logger.warning(
                            "Gemini request failed", extra={"model": model, "error": str(exc)}
                        )
                        raise LLMProviderError(_describe(exc)) from exc
                    logger.warning(
                        "Gemini transient error",
                        extra={"model": model, "attempt": attempt + 1, "error": str(exc)[:200]},
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._retry_base_delay * 2**attempt)
        assert last_exc is not None
        raise LLMProviderError(_describe(last_exc)) from last_exc

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        client = self._get_client()
        config = self._config(system)

        async def call(model: str) -> str:
            response = await client.aio.models.generate_content(
                model=model, contents=prompt, config=config
            )
            return response.text or ""

        return await self._with_resilience(call)

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        client = self._get_client()
        config = self._config(system)

        async def open_stream(model: str) -> tuple[AsyncIterator[Any], str | None]:
            # Read the first non-empty chunk inside the retry loop: overload errors
            # surface here, and retrying is only safe before any text reaches the user.
            response_stream = await client.aio.models.generate_content_stream(
                model=model, contents=prompt, config=config
            )
            iterator = aiter(response_stream)
            async for chunk in iterator:
                if chunk.text:
                    return iterator, chunk.text
            return iterator, None

        iterator, first = await self._with_resilience(open_stream)
        if first is None:
            return
        yield first
        try:
            async for chunk in iterator:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            logger.warning("Gemini stream interrupted", extra={"error": str(exc)})
            raise LLMProviderError(_describe(exc)) from exc
