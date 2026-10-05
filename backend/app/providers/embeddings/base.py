"""Embedding provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Turns text into dense vectors. Implementations must return L2-normalised vectors."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages that will be stored in the vector index."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
