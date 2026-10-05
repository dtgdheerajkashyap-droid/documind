"""Upload validation, storage and deletion of documents."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.models.document import Document
from app.providers.vectorstore.base import VectorStore
from app.repositories.document_repository import DocumentRepository
from app.services.pdf_parser import looks_like_pdf

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}
_READ_CHUNK = 1024 * 1024


class UploadRejectedError(Exception):
    def __init__(self, filename: str, reason: str) -> None:
        super().__init__(reason)
        self.filename = filename
        self.reason = reason


@dataclass(slots=True)
class StoredFile:
    doc_id: uuid.UUID
    filename: str
    path: Path
    size: int


def safe_filename(name: str | None) -> str:
    """Keep only the base name and strip characters that are awkward in UIs and paths."""
    base = Path(name or "document.pdf").name
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip() or "document.pdf"
    return base[:255]


class DocumentService:
    def __init__(self, settings: Settings, session: Session, vector_store: VectorStore) -> None:
        self.settings = settings
        self.repo = DocumentRepository(session)
        self.vector_store = vector_store

    async def store_upload(self, upload: UploadFile) -> StoredFile:
        """Validate an uploaded file and stream it to disk. Raises UploadRejectedError."""
        filename = safe_filename(upload.filename)
        if not filename.lower().endswith(".pdf"):
            raise UploadRejectedError(filename, "Only PDF files are supported.")
        if upload.content_type and upload.content_type not in ALLOWED_CONTENT_TYPES:
            raise UploadRejectedError(
                filename, f"Unsupported content type '{upload.content_type}'."
            )

        doc_id = uuid.uuid4()
        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.upload_dir / f"{doc_id}.pdf"
        limit = self.settings.max_upload_bytes
        size = 0
        try:
            with path.open("wb") as out:
                first = True
                while chunk := await upload.read(_READ_CHUNK):
                    if first:
                        if not looks_like_pdf(chunk[:5]):
                            raise UploadRejectedError(filename, "File content is not a valid PDF.")
                        first = False
                    size += len(chunk)
                    if size > limit:
                        raise UploadRejectedError(
                            filename, f"File exceeds the {self.settings.max_upload_mb} MB limit."
                        )
                    out.write(chunk)
            if size == 0:
                raise UploadRejectedError(filename, "File is empty.")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return StoredFile(doc_id=doc_id, filename=filename, path=path, size=size)

    def register(self, stored: StoredFile) -> Document:
        return self.repo.create(
            doc_id=stored.doc_id,
            filename=stored.filename,
            storage_path=str(stored.path),
            file_size=stored.size,
        )

    def list(self) -> list[Document]:
        return list(self.repo.list())

    def get(self, document_id: uuid.UUID) -> Document:
        document = self.repo.get(document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    def delete(self, document_id: uuid.UUID) -> None:
        """Remove vectors, DB rows (chunks cascade) and the stored file."""
        document = self.get(document_id)
        self.vector_store.delete_document(str(document_id))
        path = Path(document.storage_path)
        self.repo.delete(document)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete stored file", extra={"path": str(path)})
