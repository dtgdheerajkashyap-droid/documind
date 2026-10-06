"""Hybrid retrieval: dense vector search fused with keyword (BM25) ranking."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.providers.embeddings.base import EmbeddingProvider
from app.providers.vectorstore.base import VectorMatch, VectorStore
from app.services import lexical, sections

# Reciprocal-rank-fusion constant (the usual 60): a chunk's fused score is
# sum(1 / (RRF_K + rank)) over the rankings it appears in.
RRF_K = 60
# Each ranking contributes this many candidates per requested chunk.
CANDIDATES_PER_RESULT = 4
# Most text a named section ("Program 4") contributes: a lab program's code and output,
# about eight chunks.
MAX_SECTION_CHARS = 6000


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    page: int
    chunk_index: int
    text: str
    score: float  # cosine similarity to the query
    keyword_match: bool = False  # every key term of the query found, as a phrase


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
        """Top-k chunks, best first, by reciprocal rank fusion of dense and keyword rankings.

        Dense search finds passages that mean the same thing; keyword search finds the
        ones that literally name what was asked for ("Program 1", "E450"), which
        embeddings of code- or table-heavy chunks often miss.
        """
        candidates = top_k * CANDIDATES_PER_RESULT
        embedding = self.embedder.embed_query(query)
        dense = self.vector_store.query(
            embedding, top_k=candidates, workspace_id=workspace_id, document_ids=document_ids
        )
        corpus = self.vector_store.scan(workspace_id=workspace_id, document_ids=document_ids)
        titles, section = _sections(corpus, lexical.query_labels(query))
        hits = lexical.rank(
            query,
            [m.text for m in corpus],
            limit=candidates,
            contexts=[titles.get(m.id) for m in corpus],
        )

        fused: dict[str, float] = {}
        matches: dict[str, VectorMatch] = {}
        for rank, match in enumerate(dense):
            fused[match.id] = 1 / (RRF_K + rank + 1)
            matches[match.id] = match
        strong: set[str] = set()
        for rank, hit in enumerate(hits):
            match = corpus[hit.index]
            fused[match.id] = fused.get(match.id, 0.0) + 1 / (RRF_K + rank + 1)
            matches.setdefault(match.id, match)
            if hit.strong:
                strong.add(match.id)

        # Passages that literally name what was asked for come first: fusion alone can bury
        # them under chunks that rank moderately in both lists (e.g. every "Program N"
        # chunk contains a "1" somewhere in its code).
        by_fused = sorted(fused, key=lambda id_: fused[id_], reverse=True)
        strong_first = [corpus[h.index].id for h in hits if corpus[h.index].id in strong]
        # ...but leave room for semantic matches (explanations elsewhere in the document).
        strong_first = strong_first[: (top_k + 1) // 2]
        # A question about "Program 4" gets all of Program 4, in order, on top of the usual
        # results (the section counts as one of them).
        by_id = {m.id: m for m in corpus}
        for id_ in section:
            matches.setdefault(id_, by_id[id_])
        strong.update(section)
        limit = top_k + max(len(section) - 1, 0)
        selected = list(dict.fromkeys(section + strong_first + by_fused))[:limit]
        # Keyword-only hits have no similarity score yet: compute it from the stored vectors.
        dense_ids = {m.id for m in dense}
        stored = self.vector_store.embeddings([id_ for id_ in selected if id_ not in dense_ids])
        scores = {
            id_: sum(a * b for a, b in zip(embedding, vector, strict=True))
            for id_, vector in stored.items()
        }
        return [_to_chunk(matches[id_], scores.get(id_), id_ in strong) for id_ in selected]


def _sections(
    corpus: list[VectorMatch], labels: set[tuple[str, str]]
) -> tuple[dict[str, str], list[str]]:
    """Section titles by chunk id, and the chunks of the sections the query names
    ("Program 4"), in document order and at most MAX_SECTION_CHARS of text."""
    by_document: dict[str, list[VectorMatch]] = defaultdict(list)
    for match in corpus:
        by_document[str(match.metadata.get("document_id", ""))].append(match)

    titles: dict[str, str] = {}
    named: list[str] = []
    for chunks in by_document.values():
        chunks.sort(key=lambda m: int(m.metadata.get("chunk_index", 0)))
        texts = [m.text for m in chunks]
        for id_, title in zip((m.id for m in chunks), sections.chunk_titles(texts), strict=True):
            if title:
                titles[id_] = title
        if labels:
            for found in sections.find_sections(texts):
                if found.label in labels:
                    named.extend(chunks[p].id for p in found.chunks)

    texts_by_id = {m.id: m.text for m in corpus}
    kept: list[str] = []
    size = 0
    for id_ in named:
        size += len(texts_by_id[id_])
        if kept and size > MAX_SECTION_CHARS:
            break
        kept.append(id_)
    return titles, kept


def _to_chunk(match: VectorMatch, score: float | None, keyword_match: bool) -> RetrievedChunk:
    metadata = match.metadata
    return RetrievedChunk(
        chunk_id=match.id,
        document_id=str(metadata.get("document_id", "")),
        filename=str(metadata.get("filename", "unknown")),
        page=int(metadata.get("page", 0)),
        chunk_index=int(metadata.get("chunk_index", 0)),
        text=match.text,
        score=round(match.score if score is None else score, 4),
        keyword_match=keyword_match,
    )
