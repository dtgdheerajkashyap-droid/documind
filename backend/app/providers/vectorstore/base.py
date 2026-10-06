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
        self,
        embedding: list[float],
        top_k: int,
        *,
        workspace_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[VectorMatch]:
        """Return the `top_k` nearest records, optionally restricted to a workspace and/or
        specific documents."""

    @abstractmethod
    def scan(
        self, *, workspace_id: str | None = None, document_ids: list[str] | None = None
    ) -> list[VectorMatch]:
        """Every record in a workspace and/or set of documents (score 0), for keyword search."""

    @abstractmethod
    def embeddings(self, ids: list[str]) -> dict[str, list[float]]:
        """Stored embeddings by record id."""

    @abstractmethod
    def delete_document(self, document_id: str) -> None: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def count_document(self, document_id: str) -> int:
        """Number of vectors stored for one document."""

    def healthcheck(self) -> bool:
        try:
            self.count()
        except Exception:
            return False
        return True
