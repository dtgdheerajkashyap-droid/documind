"""Semantic retrieval over the vector store."""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.embeddings.base import EmbeddingProvider
from app.providers.vectorstore.base import VectorStore


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    page: int
    chunk_index: int
    text: str
    score: float


class Retriever:
    def __init__(self, embedder: EmbeddingProvider, vector_store: VectorStore) -> None:
        self.embedder = embedder
        self.vector_store = vector_store

    def retrieve(
        self,
        query: str,
        top_k: int,
        document_ids: list[str] | None = None,
        *,
        workspace_id: str | None = None,
    ) -> list[RetrievedChunk]:
        """Top-k chunks by cosine similarity, best first."""
        embedding = self.embedder.embed_query(query)
        matches = self.vector_store.query(
            embedding, top_k=top_k, workspace_id=workspace_id, document_ids=document_ids
        )
        chunks = [
            RetrievedChunk(
                chunk_id=m.id,
                document_id=str(m.metadata.get("document_id", "")),
                filename=str(m.metadata.get("filename", "unknown")),
                page=int(m.metadata.get("page", 0)),
                chunk_index=int(m.metadata.get("chunk_index", 0)),
                text=m.text,
                score=round(m.score, 4),
            )
            for m in matches
        ]
        return sorted(chunks, key=lambda c: c.score, reverse=True)
