import uuid
from pathlib import Path

import pymupdf

from app.core.container import AppContainer
from app.core.workspace import DEFAULT_WORKSPACE_ID
from app.db.session import session_scope
from app.models.document import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.services.pdf_parser import extract_pages
from tests.conftest import SAMPLE_PAGES, register_document


def _load(container: AppContainer, doc_id: uuid.UUID):
    with session_scope(container.session_factory) as session:
        repo = DocumentRepository(session)
        return repo.get(doc_id), list(repo.chunks_for(doc_id))


def test_extract_pages_returns_text_per_page(sample_pdf: Path) -> None:
    pages = extract_pages(sample_pdf)
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert "founded in 2011" in pages[0].text
    assert "30 days" in pages[1].text


def test_ingest_sample_pdf_end_to_end(container: AppContainer, sample_pdf: Path) -> None:
    doc_id = register_document(container, sample_pdf)

    container.ingestion.ingest(doc_id)

    document, chunks = _load(container, doc_id)
    assert document.status == DocumentStatus.READY
    assert document.error_message is None
    assert document.page_count == len(SAMPLE_PAGES)
    assert document.chunk_count == len(chunks) > 0
    assert container.vector_store.count() == len(chunks)
    assert {c.page_number for c in chunks} == {1, 2, 3}
    assert all(c.char_count == len(c.text) <= container.settings.chunk_size for c in chunks)

    # Vectors carry the metadata needed for citations, keyed by the chunk's DB id.
    match = container.vector_store.query(
        container.embedder.embed_query("refund unopened bags"), top_k=1
    )[0]
    assert match.metadata == {
        "workspace_id": str(DEFAULT_WORKSPACE_ID),
        "document_id": str(doc_id),
        "filename": sample_pdf.name,
        "page": 2,
        "chunk_index": match.metadata["chunk_index"],
    }
    assert match.id in {str(c.id) for c in chunks}


def test_pdf_without_text_is_marked_failed(container: AppContainer, tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    doc_id = register_document(container, path)

    container.ingestion.ingest(doc_id)

    document, chunks = _load(container, doc_id)
    assert document.status == DocumentStatus.FAILED
    assert "No extractable text" in document.error_message
    assert chunks == []
    assert container.vector_store.count() == 0


def test_corrupt_pdf_is_marked_failed(container: AppContainer, tmp_path: Path) -> None:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not really a pdf")
    doc_id = register_document(container, path)

    container.ingestion.ingest(doc_id)

    document, _ = _load(container, doc_id)
    assert document.status == DocumentStatus.FAILED
    assert document.error_message


def test_ingesting_unknown_document_is_a_noop(container: AppContainer) -> None:
    container.ingestion.ingest(uuid.uuid4())  # must not raise
    assert container.vector_store.count() == 0
