"""Vector store interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VectorRecord:
    id: str
    embedding: list[float]
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VectorMatch:
    id: str
    text: str
    metadata: dict[str, Any]
    score: float  # cosine similarity in [-1, 1]; higher is more similar


class VectorStore(ABC):
    @abstractmethod
    def add(self, records: list[VectorRecord]) -> None: ...

    @abstractmethod
    def query(
        self, embedding: list[float], top_k: int, document_ids: list[str] | None = None
    ) -> list[VectorMatch]:
        """Return the `top_k` nearest records, optionally restricted to some documents."""

    @abstractmethod
    def delete_document(self, document_id: str) -> None: ...

    @abstractmethod
    def count(self) -> int: ...

    def healthcheck(self) -> bool:
        try:
            self.count()
        except Exception:
            return False
        return True
