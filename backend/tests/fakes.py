"""Deterministic test doubles for the embedding model and the LLM.

The fake embedder is a hashed bag-of-words: texts that share words get similar
vectors. That keeps retrieval tests meaningful while running offline in
milliseconds, without downloading the real model.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import AsyncIterator, Callable

from app.core.errors import LLMNotConfiguredError
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "the", "to", "what", "when", "which", "who", "with",
}  # fmt: skip


class HashingEmbeddings(EmbeddingProvider):
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @property
    def model_name(self) -> str:
        return "fake-hashing-embeddings"

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            if token in _STOPWORDS:
                continue
            bucket = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dim
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FakeLLM(LLMProvider):
    """Scripted LLM. `responder(prompt, system)` decides the reply; calls are recorded."""

    def __init__(
        self, responder: Callable[[str, str | None], str] | None = None, *, configured: bool = True
    ) -> None:
        self.responder = responder or (lambda prompt, system: "The answer is in the documents [1].")
        self.configured = configured
        self.calls: list[tuple[str, str | None]] = []

    @property
    def name(self) -> str:
        return "fake:llm"

    def ensure_configured(self) -> None:
        if not self.configured:
            raise LLMNotConfiguredError("GEMINI_API_KEY is not set.")

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        return self.responder(prompt, system)

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        self.calls.append((prompt, system))
        reply = self.responder(prompt, system)
        for i in range(0, len(reply), 8):  # emit in small pieces like a real stream
            yield reply[i : i + 8]
