"""Data access for documents and chunks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Chunk, Document, DocumentStatus


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, *, filename: str, storage_path: str, file_size: int, doc_id: uuid.UUID | None = None
    ) -> Document:
        document = Document(
            id=doc_id or uuid.uuid4(),
            filename=filename,
            storage_path=storage_path,
            file_size=file_size,
            status=DocumentStatus.QUEUED,
            chunk_count=0,
        )
        self.session.add(document)
        self.session.flush()
        return document

    def get(self, document_id: uuid.UUID) -> Document | None:
        return self.session.get(Document, document_id)

    def list(self) -> Sequence[Document]:
        return self.session.scalars(select(Document).order_by(Document.created_at.desc())).all()

    def ready_ids(self, among: Sequence[uuid.UUID] | None = None) -> list[uuid.UUID]:
        stmt = select(Document.id).where(Document.status == DocumentStatus.READY)
        if among:
            stmt = stmt.where(Document.id.in_(among))
        return list(self.session.scalars(stmt).all())

    def set_status(
        self, document: Document, status: DocumentStatus, error_message: str | None = None
    ) -> None:
        document.status = status
        document.error_message = error_message
        self.session.flush()

    def delete(self, document: Document) -> None:
        self.session.delete(document)
        self.session.flush()

    # --- Chunks ----------------------------------------------------------
    def add_chunks(self, chunks: list[Chunk]) -> None:
        self.session.add_all(chunks)
        self.session.flush()

    def chunks_for(self, document_id: uuid.UUID) -> Sequence[Chunk]:
        return self.session.scalars(
            select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
        ).all()
