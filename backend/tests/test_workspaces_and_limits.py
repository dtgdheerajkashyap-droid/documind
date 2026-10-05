"""Workspace isolation, abuse limits, sample documents and startup recovery."""

import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.container import AppContainer
from app.core.rate_limit import client_key
from app.db.session import session_scope
from app.main import create_app
from app.models.document import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from tests.conftest import SAMPLE_PAGES, ingest_document, make_pdf, parse_sse, register_document

WS_A = {"X-Workspace-Id": str(uuid.uuid4())}
WS_B = {"X-Workspace-Id": str(uuid.uuid4())}


def _upload(client: TestClient, path: Path, headers: dict[str, str]):
    with path.open("rb") as fh:
        return client.post(
            "/api/documents",
            files=[("files", (path.name, fh, "application/pdf"))],
            headers=headers,
        )


def _wait_ready(client: TestClient, doc_id: str, headers: dict[str, str]) -> dict:
    for _ in range(200):
        doc = client.get(f"/api/documents/{doc_id}", headers=headers).json()
        if doc["status"] in ("ready", "failed"):
            return doc
        time.sleep(0.05)
    raise AssertionError("ingestion did not finish")


# --- Workspace isolation ---------------------------------------------------


def test_documents_are_private_to_their_workspace(client: TestClient, sample_pdf: Path) -> None:
    doc = _upload(client, sample_pdf, WS_A).json()["documents"][0]
    _wait_ready(client, doc["id"], WS_A)

    assert [d["id"] for d in client.get("/api/documents", headers=WS_A).json()] == [doc["id"]]
    assert client.get("/api/documents", headers=WS_B).json() == []
    assert client.get(f"/api/documents/{doc['id']}", headers=WS_B).status_code == 404
    assert client.delete(f"/api/documents/{doc['id']}", headers=WS_B).status_code == 404
    assert client.get(f"/api/documents/{doc['id']}", headers=WS_A).status_code == 200


def test_chat_only_retrieves_from_own_workspace(client: TestClient, sample_pdf: Path) -> None:
    doc = _upload(client, sample_pdf, WS_A).json()["documents"][0]
    _wait_ready(client, doc["id"], WS_A)
    question = {"question": "What is the refund policy for unopened coffee bags?"}

    own = parse_sse(client.post("/api/chat", json=question, headers=WS_A).text)
    other = parse_sse(client.post("/api/chat", json=question, headers=WS_B).text)

    assert own[-1][1]["refused"] is False
    assert other[-1][1]["refused"] is True  # B cannot see A's documents


def test_document_filter_cannot_reach_other_workspaces(
    client: TestClient, sample_pdf: Path
) -> None:
    doc = _upload(client, sample_pdf, WS_A).json()["documents"][0]
    _wait_ready(client, doc["id"], WS_A)
    body = {"question": "What is the refund policy?", "document_ids": [doc["id"]]}

    events = parse_sse(client.post("/api/chat", json=body, headers=WS_B).text)
    assert events[-1][1]["refused"] is True


def test_sessions_are_private_to_their_workspace(client: TestClient) -> None:
    events = parse_sse(client.post("/api/chat", json={"question": "hi"}, headers=WS_A).text)
    session_id = events[0][1]["session_id"]

    assert client.get("/api/sessions", headers=WS_B).json() == []
    assert client.get(f"/api/sessions/{session_id}", headers=WS_B).status_code == 404
    assert client.delete(f"/api/sessions/{session_id}", headers=WS_B).status_code == 404
    follow_up = {"question": "and?", "session_id": session_id}
    assert client.post("/api/chat", json=follow_up, headers=WS_B).status_code == 404
    assert len(client.get("/api/sessions", headers=WS_A).json()) == 1


def test_invalid_workspace_header_is_rejected(client: TestClient) -> None:
    response = client.get("/api/documents", headers={"X-Workspace-Id": "not-a-uuid"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_workspace"


# --- Upload limits ---------------------------------------------------------


def test_duplicate_upload_is_rejected(client: TestClient, sample_pdf: Path) -> None:
    first = _upload(client, sample_pdf, WS_A)
    assert first.status_code == 201

    second = _upload(client, sample_pdf, WS_A)
    assert second.status_code == 400
    assert "already uploaded" in second.json()["error"]["details"][0]["reason"]
    # The same file is fine in another workspace.
    assert _upload(client, sample_pdf, WS_B).status_code == 201


def test_workspace_document_quota(container: AppContainer, tmp_path: Path) -> None:
    container.settings.max_documents_per_workspace = 2
    with TestClient(create_app(container)) as client:
        for i in range(2):
            pdf = make_pdf(tmp_path / f"doc{i}.pdf", [f"Document number {i} about topic {i}."])
            assert _upload(client, pdf, WS_A).status_code == 201
        third = make_pdf(tmp_path / "doc3.pdf", ["A third document."])
        response = _upload(client, third, WS_A)

    assert response.status_code == 400
    assert "maximum of 2 documents" in response.json()["error"]["message"]


def test_upload_rate_limit(container: AppContainer, tmp_path: Path) -> None:
    container.settings.upload_rate_limit_per_minute = 2
    container.__post_init__()
    with TestClient(create_app(container)) as client:
        codes = []
        for i in range(3):
            pdf = make_pdf(tmp_path / f"r{i}.pdf", [f"Rate limit document {i}."])
            codes.append(_upload(client, pdf, WS_A).status_code)

    assert codes == [201, 201, 429]


def test_oversized_request_rejected_from_content_length(container: AppContainer) -> None:
    container.settings.max_request_mb = 1
    with TestClient(create_app(container)) as client:
        body = b"%PDF-" + b"0" * (2 * 1024 * 1024)
        response = client.post(
            "/api/documents", files=[("files", ("big.pdf", body, "application/pdf"))]
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_oversized_streamed_request_rejected_without_content_length(
    container: AppContainer,
) -> None:
    container.settings.max_request_mb = 1

    def chunks():
        yield b'--b\r\nContent-Disposition: form-data; name="files"; filename="x.pdf"\r\n'
        yield b"Content-Type: application/pdf\r\n\r\n%PDF-"
        for _ in range(3):
            yield b"0" * (1024 * 1024)

    with TestClient(create_app(container)) as client:
        response = client.post(
            "/api/documents",
            content=chunks(),  # streamed with chunked encoding: no Content-Length
            headers={"content-type": "multipart/form-data; boundary=b"},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert list(container.settings.upload_dir.glob("*.pdf")) == []


# --- Sample documents --------------------------------------------------------


def test_sample_documents_can_be_added_once(client: TestClient) -> None:
    response = client.post("/api/documents/samples", headers=WS_A)
    assert response.status_code == 201
    added = response.json()["documents"]
    assert {d["filename"] for d in added} == {"atlas7_manual.pdf", "northwind_handbook.pdf"}
    for doc in added:
        assert _wait_ready(client, doc["id"], WS_A)["status"] == "ready"

    again = client.post("/api/documents/samples", headers=WS_A).json()
    assert again["documents"] == []
    assert len(again["rejected"]) == 2


# --- Proxy headers -------------------------------------------------------------


def _request(xff: str | None, peer: str = "10.0.0.1") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_forwarded_for_is_ignored_unless_proxies_are_trusted() -> None:
    assert client_key(_request("1.2.3.4"), trusted_proxy_hops=0) == "10.0.0.1"


def test_forwarded_for_uses_entry_added_by_trusted_proxy() -> None:
    # The client forged "6.6.6.6"; the trusted proxy appended the real address.
    request = _request("6.6.6.6, 203.0.113.7")
    assert client_key(request, trusted_proxy_hops=1) == "203.0.113.7"
    assert client_key(_request(None), trusted_proxy_hops=1) == "10.0.0.1"


# --- Startup recovery ------------------------------------------------------


def test_interrupted_uploads_are_requeued_or_failed(
    container: AppContainer, sample_pdf: Path, tmp_path: Path
) -> None:
    survivor = register_document(container, sample_pdf)
    gone = tmp_path / "gone.pdf"
    make_pdf(gone, ["temporary"])
    lost = register_document(container, gone)
    gone.unlink()

    requeue = container.ingestion.interrupted_documents()

    assert requeue == [survivor]
    with session_scope(container.session_factory) as session:
        repo = DocumentRepository(session)
        assert repo.get(survivor).status == DocumentStatus.QUEUED
        lost_doc = repo.get(lost)
        assert lost_doc.status == DocumentStatus.FAILED
        assert "upload it again" in lost_doc.error_message


def test_missing_vectors_are_rebuilt_from_postgres(
    container: AppContainer, sample_pdf: Path
) -> None:
    doc_id = ingest_document(container, sample_pdf)
    expected = container.vector_store.count_document(str(doc_id))
    sample_pdf.unlink()  # the original file is not needed for re-indexing
    container.vector_store.delete_document(str(doc_id))  # simulate a wiped disk
    assert container.retriever.retrieve("refund unopened bags", 3) == []

    assert container.ingestion.reindex_missing() == 1

    assert container.vector_store.count_document(str(doc_id)) == expected
    results = container.retriever.retrieve("refund unopened bags", 3)
    assert results[0].page == 2
    assert SAMPLE_PAGES[1][:20] in results[0].text
    assert container.ingestion.reindex_missing() == 0  # nothing left to do
