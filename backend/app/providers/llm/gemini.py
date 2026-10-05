"""Google Gemini provider (uses the official `google-genai` SDK)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.core.errors import LLMNotConfiguredError, LLMProviderError
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

MISSING_KEY_MESSAGE = (
    "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey, "
    "add GEMINI_API_KEY=<your key> to your .env file, and restart the backend."
)


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        temperature: float = 0.1,
        max_output_tokens: int = 1024,
        thinking_budget: int | None = 0,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._thinking_budget = thinking_budget
        self._timeout_ms = int(timeout_seconds * 1000)
        self._client: Any = None

    @property
    def name(self) -> str:
        return f"gemini:{self._model}"

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

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        client = self._get_client()
        try:
            response = await client.aio.models.generate_content(
                model=self._model, contents=prompt, config=self._config(system)
            )
        except Exception as exc:  # SDK raises a variety of error types
            logger.warning("Gemini request failed", extra={"error": str(exc)})
            raise LLMProviderError(f"Gemini request failed: {exc}") from exc
        return response.text or ""

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        client = self._get_client()
        try:
            response_stream = await client.aio.models.generate_content_stream(
                model=self._model, contents=prompt, config=self._config(system)
            )
            async for chunk in response_stream:
                if chunk.text:
                    yield chunk.text
        except LLMNotConfiguredError:
            raise
        except Exception as exc:
            logger.warning("Gemini streaming failed", extra={"error": str(exc)})
            raise LLMProviderError(f"Gemini request failed: {exc}") from exc
