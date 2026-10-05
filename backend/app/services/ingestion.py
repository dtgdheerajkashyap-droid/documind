"""Background ingestion pipeline: PDF -> pages -> chunks -> embeddings -> Chroma + Postgres."""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import IngestionError
from app.db.session import session_scope
from app.models.document import Chunk, DocumentStatus
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.vectorstore.base import VectorRecord, VectorStore
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import chunk_pages
from app.services.pdf_parser import extract_pages

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        embedder: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.embedder = embedder
        self.vector_store = vector_store

    def ingest(self, document_id: uuid.UUID) -> None:
        """Process one queued document. Never raises: failures are recorded on the document."""
        started = time.perf_counter()
        with session_scope(self.session_factory) as session:
            repo = DocumentRepository(session)
            document = repo.get(document_id)
            if document is None:
                logger.warning(
                    "Document vanished before ingestion", extra={"doc": str(document_id)}
                )
                return
            repo.set_status(document, DocumentStatus.PROCESSING)
            storage_path, filename = document.storage_path, document.filename

        try:
            page_count, chunk_count = self._process(document_id, Path(storage_path), filename)
        except Exception as exc:
            reason = str(exc) if isinstance(exc, IngestionError) else f"Unexpected error: {exc}"
            logger.exception("Ingestion failed", extra={"doc": str(document_id)})
            self._safe_delete_vectors(document_id)
            with session_scope(self.session_factory) as session:
                repo = DocumentRepository(session)
                document = repo.get(document_id)
                if document is not None:
                    repo.set_status(document, DocumentStatus.FAILED, reason[:2000])
            return

        logger.info(
            "Ingestion finished",
            extra={
                "doc": str(document_id),
                "doc_filename": filename,
                "pages": page_count,
                "chunks": chunk_count,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )

    def _process(self, document_id: uuid.UUID, path: Path, filename: str) -> tuple[int, int]:
        pages = extract_pages(path)
        if not pages:
            raise IngestionError("The PDF has no pages.")
        chunks = chunk_pages(pages, self.settings.chunk_size, self.settings.chunk_overlap)
        if not chunks:
            raise IngestionError(
                "No extractable text found. The PDF may be scanned images (OCR is not supported)."
            )

        embeddings = self.embedder.embed_documents([c.text for c in chunks])
        chunk_ids = [uuid.uuid4() for _ in chunks]
        self.vector_store.add(
            [
                VectorRecord(
                    id=str(chunk_id),
                    embedding=embedding,
                    text=chunk.text,
                    metadata={
                        "document_id": str(document_id),
                        "filename": filename,
                        "page": chunk.page_number,
                        "chunk_index": chunk.chunk_index,
                    },
                )
                for chunk_id, chunk, embedding in zip(chunk_ids, chunks, embeddings, strict=True)
            ]
        )

        with session_scope(self.session_factory) as session:
            repo = DocumentRepository(session)
            document = repo.get(document_id)
            if document is None:
                # Deleted while we were processing: don't leave orphaned vectors behind.
                self._safe_delete_vectors(document_id)
                return len(pages), 0
            repo.add_chunks(
                [
                    Chunk(
                        id=chunk_id,
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        char_count=len(chunk.text),
                    )
                    for chunk_id, chunk in zip(chunk_ids, chunks, strict=True)
                ]
            )
            document.page_count = len(pages)
            document.chunk_count = len(chunks)
            repo.set_status(document, DocumentStatus.READY)
        return len(pages), len(chunks)

    def _safe_delete_vectors(self, document_id: uuid.UUID) -> None:
        try:
            self.vector_store.delete_document(str(document_id))
        except Exception:
            logger.exception("Failed to clean up vectors", extra={"doc": str(document_id)})
