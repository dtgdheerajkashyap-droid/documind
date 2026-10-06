"""Persistent local vector store backed by ChromaDB."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.providers.vectorstore.base import VectorMatch, VectorRecord, VectorStore


class ChromaVectorStore(VectorStore):
    """Stores chunk embeddings in a cosine-distance HNSW index on local disk.

    We always pass pre-computed embeddings, so Chroma's own embedding function
    is never used.
    """

    _ADD_BATCH = 1000

    def __init__(self, persist_dir: Path | str, collection_name: str) -> None:
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}, embedding_function=None
        )
        self._lock = threading.Lock()

    def add(self, records: list[VectorRecord]) -> None:
        with self._lock:
            for start in range(0, len(records), self._ADD_BATCH):
                batch = records[start : start + self._ADD_BATCH]
                self._collection.add(
                    ids=[r.id for r in batch],
                    embeddings=[r.embedding for r in batch],
                    documents=[r.text for r in batch],
                    metadatas=[r.metadata for r in batch],
                )

    def query(
        self,
        embedding: list[float],
        top_k: int,
        *,
        workspace_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[VectorMatch]:
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where=_where(workspace_id, document_ids),
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            VectorMatch(
                id=ids[i],
                text=documents[i] or "",
                metadata=dict(metadatas[i] or {}),
                # Chroma's cosine "distance" is 1 - cosine similarity.
                score=1.0 - float(distances[i]),
            )
            for i in range(len(ids))
        ]

    def scan(
        self, *, workspace_id: str | None = None, document_ids: list[str] | None = None
    ) -> list[VectorMatch]:
        result = self._collection.get(
            where=_where(workspace_id, document_ids), include=["documents", "metadatas"]
        )
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        return [
            VectorMatch(
                id=id_, text=documents[i] or "", metadata=dict(metadatas[i] or {}), score=0.0
            )
            for i, id_ in enumerate(result["ids"])
        ]

    def embeddings(self, ids: list[str]) -> dict[str, list[float]]:
        if not ids:
            return {}
        result = self._collection.get(ids=ids, include=["embeddings"])
        vectors = result.get("embeddings")
        if vectors is None:
            return {}
        return {id_: [float(x) for x in vectors[i]] for i, id_ in enumerate(result["ids"])}

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            self._collection.delete(where={"document_id": document_id})

    def count(self) -> int:
        return self._collection.count()

    def count_document(self, document_id: str) -> int:
        return len(self._collection.get(where={"document_id": document_id}, include=[])["ids"])


def _where(workspace_id: str | None, document_ids: list[str] | None) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = []
    if workspace_id is not None:
        conditions.append({"workspace_id": workspace_id})
    if document_ids:
        conditions.append(
            {"document_id": document_ids[0]}
            if len(document_ids) == 1
            else {"document_id": {"$in": document_ids}}
        )
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions} if conditions else None
