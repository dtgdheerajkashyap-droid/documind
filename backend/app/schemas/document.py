from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_size: int
    status: DocumentStatus
    error_message: str | None
    page_count: int | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class RejectedFile(BaseModel):
    filename: str
    reason: str


class DocumentUploadResponse(BaseModel):
    documents: list[DocumentOut]
    rejected: list[RejectedFile]
