"""Ollama provider for fully local LLMs (e.g. `ollama pull llama3.1:8b`)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.errors import LLMProviderError
from app.providers.llm.base import LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        temperature: float = 0.1,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"

    def _payload(self, prompt: str, system: str | None, stream: bool) -> dict[str, Any]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": self._temperature, "num_predict": self._max_output_tokens},
        }

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat", json=self._payload(prompt, system, False)
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Ollama request failed: {exc}") from exc
        return response.json().get("message", {}).get("content", "")

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream(
                    "POST", f"{self._base_url}/api/chat", json=self._payload(prompt, system, True)
                ) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    text = data.get("message", {}).get("content", "")
                    if text:
                        yield text
                    if data.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Ollama request failed: {exc}") from exc
