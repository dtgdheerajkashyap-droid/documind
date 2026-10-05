"""Ingestion pipeline: PDF -> pages -> chunks -> embeddings -> Chroma + Postgres.

Postgres is the source of truth: it stores every chunk's text, so the Chroma index
is derived data that can be rebuilt (`reindex_missing`). That matters on hosts
with ephemeral disks, where a restart wipes the vector index and uploaded files.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import IngestionError
from app.db.session import session_scope
from app.models.document import Chunk, Document, DocumentStatus
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.vectorstore.base import VectorRecord, VectorStore
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import chunk_pages
from app.services.pdf_parser import extract_pages

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = (
    "Processing was interrupted by a server restart and the uploaded file is no longer "
    "available. Please upload it again."
)


def vector_metadata(document: Document, page: int, chunk_index: int) -> dict[str, str | int]:
    return {
        "workspace_id": str(document.workspace_id),
        "document_id": str(document.id),
        "filename": document.filename,
        "page": page,
        "chunk_index": chunk_index,
    }


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
            page_count, chunk_count = self._process(document_id, Path(storage_path))
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

    def _process(self, document_id: uuid.UUID, path: Path) -> tuple[int, int]:
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

        with session_scope(self.session_factory) as session:
            document = DocumentRepository(session).get(document_id)
            if document is None:  # deleted while we were embedding
                return len(pages), 0
            records = [
                VectorRecord(
                    id=str(chunk_id),
                    embedding=embedding,
                    text=chunk.text,
                    metadata=vector_metadata(document, chunk.page_number, chunk.chunk_index),
                )
                for chunk_id, chunk, embedding in zip(chunk_ids, chunks, embeddings, strict=True)
            ]
        self.vector_store.add(records)

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

    # --- Recovery --------------------------------------------------------
    def interrupted_documents(self) -> list[uuid.UUID]:
        """After a restart: documents left queued/processing.

        Returns the ones whose file still exists (to re-queue) and marks the rest failed.
        """
        requeue: list[uuid.UUID] = []
        with session_scope(self.session_factory) as session:
            repo = DocumentRepository(session)
            for document in repo.with_status(DocumentStatus.QUEUED, DocumentStatus.PROCESSING):
                if Path(document.storage_path).is_file():
                    repo.set_status(document, DocumentStatus.QUEUED)
                    requeue.append(document.id)
                else:
                    repo.set_status(document, DocumentStatus.FAILED, INTERRUPTED_MESSAGE)
        return requeue

    def reindex_missing(self) -> int:
        """Rebuild vectors for ready documents whose vectors are missing or incomplete.

        Re-embeds the chunk text stored in Postgres, so the original PDF is not needed.
        Returns the number of documents re-indexed.
        """
        with session_scope(self.session_factory) as session:
            ready = [
                (d.id, d.chunk_count)
                for d in DocumentRepository(session).with_status(DocumentStatus.READY)
            ]
        rebuilt = 0
        for document_id, chunk_count in ready:
            if self.vector_store.count_document(str(document_id)) == chunk_count:
                continue
            with session_scope(self.session_factory) as session:
                repo = DocumentRepository(session)
                document = repo.get(document_id)
                if document is None:
                    continue
                chunks = list(repo.chunks_for(document_id))
                embeddings = self.embedder.embed_documents([c.text for c in chunks])
                records = [
                    VectorRecord(
                        id=str(c.id),
                        embedding=e,
                        text=c.text,
                        metadata=vector_metadata(document, c.page_number, c.chunk_index),
                    )
                    for c, e in zip(chunks, embeddings, strict=True)
                ]
            self._safe_delete_vectors(document_id)
            self.vector_store.add(records)
            rebuilt += 1
            logger.info(
                "Re-indexed document", extra={"doc": str(document_id), "chunks": len(records)}
            )
        return rebuilt

    def _safe_delete_vectors(self, document_id: uuid.UUID) -> None:
        try:
            self.vector_store.delete_document(str(document_id))
        except Exception:
            logger.exception("Failed to clean up vectors", extra={"doc": str(document_id)})


class IngestionQueue:
    """Runs ingestion jobs one at a time on a background thread.

    A single worker keeps CPU and memory predictable: embedding several large PDFs
    in parallel on a small server would only make every job slower.
    """

    def __init__(self, service: IngestionService) -> None:
        self.service = service
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingestion")
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, document_id: uuid.UUID) -> Future[None]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Ingestion queue is shut down")
            return self._executor.submit(self.service.ingest, document_id)

    def recover(self) -> None:
        """Startup recovery: re-queue interrupted uploads, then rebuild missing vectors."""
        try:
            for document_id in self.service.interrupted_documents():
                self.submit(document_id)
            rebuilt = self.service.reindex_missing()
            if rebuilt:
                logger.info("Vector index rebuilt from Postgres", extra={"documents": rebuilt})
        except Exception:
            logger.exception("Startup recovery failed")

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
