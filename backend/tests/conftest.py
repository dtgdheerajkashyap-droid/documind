"""Shared fixtures: an isolated app (SQLite + temporary Chroma + fakes) per test.

Set TEST_DATABASE_URL (e.g. to a Postgres URL, as CI does) to run against another database.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import AppContainer
from app.db.base import Base
from app.db.session import create_db_engine, create_session_factory
from app.main import create_app
from app.providers.vectorstore.chroma import ChromaVectorStore
from tests.fakes import FakeLLM, HashingEmbeddings

SAMPLE_PAGES = [
    "Orion Coffee Company Handbook. Orion Coffee was founded in 2011 in Portland by Maya Chen. "
    "The company roasts single-origin beans and operates twelve cafes.",
    "Refund policy. Customers may return unopened bags of coffee within 30 days of purchase "
    "for a full refund. Opened bags can be exchanged within 7 days.",
    "Employee benefits. Full-time baristas receive 20 days of paid vacation per year, "
    "health insurance, and a weekly allowance of two free pounds of coffee.",
]


def make_pdf(path: Path, pages: list[str]) -> Path:
    """Write a simple text PDF with one string per page."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 770), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "orion_handbook.pdf", SAMPLE_PAGES)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        log_format="console",
        log_level="WARNING",
        database_url=os.environ.get("TEST_DATABASE_URL")
        or f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        chroma_persist_dir=tmp_path / "chroma",
        upload_dir=tmp_path / "uploads",
        chunk_size=300,
        chunk_overlap=50,
        retrieval_min_score=0.2,
        max_upload_mb=1,
        chat_rate_limit_per_minute=100,
        gemini_api_key="test-key",
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def container(settings: Settings, fake_llm: FakeLLM) -> Iterator[AppContainer]:
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    c = AppContainer(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        embedder=HashingEmbeddings(),
        vector_store=ChromaVectorStore(settings.chroma_persist_dir, "test_chunks"),
        llm=fake_llm,
    )
    yield c
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(container: AppContainer) -> Iterator[TestClient]:
    with TestClient(create_app(container)) as test_client:
        yield test_client


@pytest.fixture
def upload(client: TestClient) -> Callable[..., dict[str, Any]]:
    """Upload a PDF through the API and wait until ingestion finishes."""

    def _upload(path: Path, wait: bool = True) -> dict[str, Any]:
        with path.open("rb") as fh:
            response = client.post(
                "/api/documents", files=[("files", (path.name, fh, "application/pdf"))]
            )
        assert response.status_code == 201, response.text
        document = response.json()["documents"][0]
        if wait:
            # TestClient runs background tasks before returning, but poll defensively.
            for _ in range(50):
                document = client.get(f"/api/documents/{document['id']}").json()
                if document["status"] in ("ready", "failed"):
                    break
                time.sleep(0.05)
        return document

    return _upload


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE response body into (event, data) pairs."""
    events = []
    for block in body.strip().split("\n\n"):
        event, data = "message", ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data += line[len("data:") :].strip()
        events.append((event, json.loads(data) if data else {}))
    return events
