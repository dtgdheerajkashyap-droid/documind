"""Document upload, listing and deletion."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Response, UploadFile, status

from app.api.deps import ContainerDep, DbDep
from app.core.errors import InvalidUploadError
from app.schemas.document import DocumentOut, DocumentUploadResponse, RejectedFile
from app.services.document_service import DocumentService, UploadRejectedError

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_FILES_PER_REQUEST = 20


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentUploadResponse)
async def upload_documents(
    container: ContainerDep,
    db: DbDep,
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(description="One or more PDF files")],
) -> DocumentUploadResponse:
    """Upload PDFs. Valid files are queued for background ingestion; invalid ones are reported."""
    if len(files) > MAX_FILES_PER_REQUEST:
        raise InvalidUploadError(f"At most {MAX_FILES_PER_REQUEST} files per upload.")

    service = DocumentService(container.settings, db, container.vector_store)
    accepted, rejected = [], []
    for upload in files:
        try:
            stored = await service.store_upload(upload)
        except UploadRejectedError as exc:
            rejected.append(RejectedFile(filename=exc.filename, reason=exc.reason))
            continue
        accepted.append(service.register(stored))

    if not accepted:
        raise InvalidUploadError(
            "No valid PDF files were uploaded.", details=[r.model_dump() for r in rejected]
        )

    # Commit before scheduling ingestion so the background task can see the rows.
    db.commit()
    ingestion = container.ingestion
    for document in accepted:
        background_tasks.add_task(ingestion.ingest, document.id)

    return DocumentUploadResponse(
        documents=[DocumentOut.model_validate(d) for d in accepted], rejected=rejected
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(container: ContainerDep, db: DbDep) -> list[DocumentOut]:
    service = DocumentService(container.settings, db, container.vector_store)
    return [DocumentOut.model_validate(d) for d in service.list()]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, container: ContainerDep, db: DbDep) -> DocumentOut:
    service = DocumentService(container.settings, db, container.vector_store)
    return DocumentOut.model_validate(service.get(document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, container: ContainerDep, db: DbDep) -> Response:
    DocumentService(container.settings, db, container.vector_store).delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
