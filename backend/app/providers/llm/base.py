"""LLM provider interface. Swap implementations with the LLM_PROVIDER env variable."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider/model identifier, e.g. "gemini:gemini-2.5-flash"."""

    def ensure_configured(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Raise LLMNotConfiguredError if the provider cannot be used (e.g. missing key)."""

    @abstractmethod
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a complete response."""

    @abstractmethod
    def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        """Yield the response incrementally as text fragments."""
