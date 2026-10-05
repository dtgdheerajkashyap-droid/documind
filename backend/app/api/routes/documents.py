"""Document upload, listing and deletion (scoped to the caller's workspace)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Request, Response, UploadFile, status

from app.api.deps import ContainerDep, DbDep
from app.core.errors import InvalidUploadError
from app.core.rate_limit import client_key
from app.core.workspace import WorkspaceDep
from app.schemas.document import DocumentOut, DocumentUploadResponse, RejectedFile
from app.services.document_service import DocumentService, UploadRejectedError

router = APIRouter(prefix="/documents", tags=["documents"])


def _service(container: ContainerDep, db: DbDep, workspace_id: uuid.UUID) -> DocumentService:
    return DocumentService(container.settings, db, container.vector_store, workspace_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentUploadResponse)
async def upload_documents(
    request: Request,
    container: ContainerDep,
    db: DbDep,
    workspace_id: WorkspaceDep,
    files: Annotated[list[UploadFile], File(description="One or more PDF files")],
) -> DocumentUploadResponse:
    """Upload PDFs. Valid files are queued for ingestion; invalid ones are reported."""
    settings = container.settings
    container.upload_rate_limiter.check(client_key(request, settings.trusted_proxy_hops))
    if len(files) > settings.max_files_per_upload:
        raise InvalidUploadError(f"At most {settings.max_files_per_upload} files per upload.")

    service = _service(container, db, workspace_id)
    service.ensure_quota()
    accepted, rejected = [], []
    for upload in files:
        if len(accepted) >= service.remaining_quota():
            rejected.append(
                RejectedFile(
                    filename=upload.filename or "file",
                    reason="Workspace document limit reached.",
                )
            )
            continue
        try:
            stored = await service.store_upload(upload)
        except UploadRejectedError as exc:
            rejected.append(RejectedFile(filename=exc.filename, reason=exc.reason))
            continue
        accepted.append(service.register(stored))
        db.flush()

    if not accepted:
        raise InvalidUploadError(
            "No valid PDF files were uploaded.", details=[r.model_dump() for r in rejected]
        )

    # Commit before queueing so the ingestion worker can see the rows.
    db.commit()
    for document in accepted:
        container.ingestion_queue.submit(document.id)

    return DocumentUploadResponse(
        documents=[DocumentOut.model_validate(d) for d in accepted], rejected=rejected
    )


@router.post("/samples", status_code=status.HTTP_201_CREATED, response_model=DocumentUploadResponse)
def add_sample_documents(
    container: ContainerDep, db: DbDep, workspace_id: WorkspaceDep
) -> DocumentUploadResponse:
    """Add the bundled sample PDFs to the workspace, so visitors can try the app instantly."""
    service = _service(container, db, workspace_id)
    added, skipped = service.add_samples()
    db.commit()
    for document in added:
        container.ingestion_queue.submit(document.id)
    return DocumentUploadResponse(
        documents=[DocumentOut.model_validate(d) for d in added],
        rejected=[
            RejectedFile(filename=name, reason="Already in your workspace or limit reached.")
            for name in skipped
        ],
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(
    container: ContainerDep, db: DbDep, workspace_id: WorkspaceDep
) -> list[DocumentOut]:
    return [DocumentOut.model_validate(d) for d in _service(container, db, workspace_id).list()]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID, container: ContainerDep, db: DbDep, workspace_id: WorkspaceDep
) -> DocumentOut:
    return DocumentOut.model_validate(_service(container, db, workspace_id).get(document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID, container: ContainerDep, db: DbDep, workspace_id: WorkspaceDep
) -> Response:
    _service(container, db, workspace_id).delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
