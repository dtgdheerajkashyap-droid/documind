from pathlib import Path

from fastapi.testclient import TestClient

from app.core.container import AppContainer


def test_upload_ingests_and_reports_ready(client: TestClient, upload, sample_pdf: Path) -> None:
    document = upload(sample_pdf)

    assert document["status"] == "ready"
    assert document["filename"] == "orion_handbook.pdf"
    assert document["page_count"] == 3
    assert document["chunk_count"] > 0


def test_upload_multiple_files_with_partial_rejection(
    client: TestClient, sample_pdf: Path, tmp_path: Path
) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("not a pdf")
    with sample_pdf.open("rb") as pdf, notes.open("rb") as txt:
        response = client.post(
            "/api/documents",
            files=[
                ("files", (sample_pdf.name, pdf, "application/pdf")),
                ("files", ("notes.txt", txt, "text/plain")),
            ],
        )

    assert response.status_code == 201
    body = response.json()
    assert [d["filename"] for d in body["documents"]] == ["orion_handbook.pdf"]
    assert body["rejected"] == [
        {"filename": "notes.txt", "reason": "Only PDF files are supported."}
    ]


def test_upload_rejects_non_pdf(client: TestClient) -> None:
    response = client.post(
        "/api/documents", files=[("files", ("image.png", b"\x89PNG....", "image/png"))]
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_upload"
    assert error["details"][0]["filename"] == "image.png"


def test_upload_rejects_fake_pdf_content(client: TestClient) -> None:
    response = client.post(
        "/api/documents", files=[("files", ("fake.pdf", b"hello world", "application/pdf"))]
    )
    assert response.status_code == 400
    assert "not a valid PDF" in response.json()["error"]["details"][0]["reason"]


def test_upload_rejects_oversized_file(client: TestClient, container: AppContainer) -> None:
    too_big = b"%PDF-1.7\n" + b"0" * (container.settings.max_upload_bytes + 1)
    response = client.post(
        "/api/documents", files=[("files", ("big.pdf", too_big, "application/pdf"))]
    )
    assert response.status_code == 400
    assert "1 MB limit" in response.json()["error"]["details"][0]["reason"]
    assert list(container.settings.upload_dir.iterdir()) == []  # partial file cleaned up


def test_upload_requires_files(client: TestClient) -> None:
    response = client.post("/api/documents")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_list_and_get_documents(client: TestClient, upload, sample_pdf: Path) -> None:
    document = upload(sample_pdf)

    listed = client.get("/api/documents").json()
    assert [d["id"] for d in listed] == [document["id"]]
    assert client.get(f"/api/documents/{document['id']}").json()["status"] == "ready"


def test_get_unknown_document_returns_404(client: TestClient) -> None:
    response = client.get("/api/documents/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Document not found.", "details": None}
    }


def test_invalid_document_id_is_a_validation_error(client: TestClient) -> None:
    response = client.get("/api/documents/not-a-uuid")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_delete_removes_rows_vectors_and_file(
    client: TestClient, upload, sample_pdf: Path, container: AppContainer
) -> None:
    document = upload(sample_pdf)
    assert container.vector_store.count() > 0

    response = client.delete(f"/api/documents/{document['id']}")

    assert response.status_code == 204
    assert container.vector_store.count() == 0
    assert client.get(f"/api/documents/{document['id']}").status_code == 404
    assert list(container.settings.upload_dir.iterdir()) == []
    assert client.delete(f"/api/documents/{document['id']}").status_code == 404
