"""Data access for documents and chunks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Chunk, Document, DocumentStatus


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        filename: str,
        storage_path: str,
        file_size: int,
        content_hash: str | None = None,
        doc_id: uuid.UUID | None = None,
    ) -> Document:
        document = Document(
            id=doc_id or uuid.uuid4(),
            workspace_id=workspace_id,
            filename=filename,
            storage_path=storage_path,
            file_size=file_size,
            content_hash=content_hash,
            status=DocumentStatus.QUEUED,
            chunk_count=0,
        )
        self.session.add(document)
        self.session.flush()
        return document

    def get(self, document_id: uuid.UUID, workspace_id: uuid.UUID | None = None) -> Document | None:
        """Fetch a document; when `workspace_id` is given, other workspaces' documents are hidden."""
        document = self.session.get(Document, document_id)
        if document is None or (workspace_id is not None and document.workspace_id != workspace_id):
            return None
        return document

    def list(self, workspace_id: uuid.UUID) -> Sequence[Document]:
        return self.session.scalars(
            select(Document)
            .where(Document.workspace_id == workspace_id)
            .order_by(Document.created_at.desc())
        ).all()

    def count(self, workspace_id: uuid.UUID) -> int:
        stmt = select(func.count(Document.id)).where(Document.workspace_id == workspace_id)
        return self.session.scalar(stmt) or 0

    def find_duplicate(self, workspace_id: uuid.UUID, content_hash: str) -> Document | None:
        """A non-failed document in the workspace with identical file content."""
        return self.session.scalars(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.content_hash == content_hash,
                Document.status != DocumentStatus.FAILED,
            )
        ).first()

    def ready_ids(
        self, workspace_id: uuid.UUID, among: Sequence[uuid.UUID] | None = None
    ) -> list[uuid.UUID]:
        stmt = select(Document.id).where(
            Document.workspace_id == workspace_id, Document.status == DocumentStatus.READY
        )
        if among:
            stmt = stmt.where(Document.id.in_(among))
        return list(self.session.scalars(stmt).all())

    def with_status(self, *statuses: DocumentStatus) -> Sequence[Document]:
        """Documents in the given states across all workspaces (used for startup recovery)."""
        return self.session.scalars(select(Document).where(Document.status.in_(statuses))).all()

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
