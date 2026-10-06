from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import REFUSAL_MESSAGE
from app.core.container import AppContainer
from app.main import create_app
from app.providers.llm.gemini import GeminiProvider
from tests.conftest import make_pdf, parse_sse
from tests.fakes import FakeLLM


def test_chat_streams_sse_events(
    client: TestClient, upload, sample_pdf: Path, fake_llm: FakeLLM
) -> None:
    upload(sample_pdf)
    fake_llm.responder = lambda prompt, system: "Orion Coffee was founded in 2011 [1]."

    response = client.post("/api/chat", json={"question": "When was Orion Coffee founded?"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert "token" in names
    assert names[-2:] == ["citations", "done"]
    done = events[-1][1]
    assert done["answer"] == "Orion Coffee was founded in 2011 [1]."
    assert done["refused"] is False
    citation = events[-2][1]["citations"][0]
    assert citation["filename"] == "orion_handbook.pdf"
    assert citation["page"] == 1


def test_chat_persists_session_history(
    client: TestClient, upload, sample_pdf: Path, fake_llm: FakeLLM
) -> None:
    upload(sample_pdf)
    fake_llm.responder = lambda prompt, system: "Within 30 days [1]."

    events = parse_sse(client.post("/api/chat", json={"question": "Refund window?"}).text)
    session_id = events[0][1]["session_id"]

    detail = client.get(f"/api/sessions/{session_id}").json()
    assert detail["title"] == "Refund window?"
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("user", "Refund window?"),
        ("assistant", "Within 30 days [1]."),
    ]
    assert detail["messages"][1]["citations"][0]["page"] == 2

    # A follow-up in the same session appends to it.
    client.post("/api/chat", json={"question": "And opened bags?", "session_id": session_id})
    assert client.get(f"/api/sessions/{session_id}").json()["message_count"] == 4


def test_chat_answers_about_a_numbered_program(
    client: TestClient, upload, tmp_path: Path, fake_llm: FakeLLM
) -> None:
    code = "X = rand(10, 1); for i = 1:10 Y(i) = X(i) * 2; end disp(Y(1));"
    upload(
        make_pdf(
            tmp_path / "lab_manual.pdf",
            [f"Program 1: Word embeddings. {code}", f"Program 2: Digit classifier. {code}"],
        )
    )
    fake_llm.responder = lambda prompt, system: "Program 1 builds word embeddings [1]."

    events = parse_sse(
        client.post("/api/chat", json={"question": "explain the first program"}).text
    )

    done = events[-1][1]
    assert done["refused"] is False
    assert events[-2][1]["citations"][0]["page"] == 1
    assert "Program 1: Word embeddings." in fake_llm.calls[-1][0]


def test_chat_refuses_when_nothing_relevant(client: TestClient, upload, sample_pdf: Path) -> None:
    upload(sample_pdf)
    events = parse_sse(
        client.post("/api/chat", json={"question": "Describe gluon lattice chromodynamics"}).text
    )
    assert events[-1][1]["answer"] == REFUSAL_MESSAGE
    assert events[-2][1]["citations"] == []


def test_chat_document_filter_with_no_ready_documents_refuses(client: TestClient) -> None:
    events = parse_sse(
        client.post(
            "/api/chat",
            json={
                "question": "What is the refund policy?",
                "document_ids": ["00000000-0000-0000-0000-000000000000"],
            },
        ).text
    )
    assert events[-1][1]["answer"] == REFUSAL_MESSAGE


def test_chat_unknown_session_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/chat", json={"question": "hi", "session_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_chat_validates_question(client: TestClient) -> None:
    assert client.post("/api/chat", json={"question": "   "}).status_code == 422
    assert client.post("/api/chat", json={"question": "x" * 2001}).status_code == 422
    assert client.post("/api/chat", json={}).status_code == 422


def test_chat_without_gemini_key_returns_clear_error(container: AppContainer) -> None:
    container.llm = GeminiProvider(api_key=None, model="gemini-2.5-flash")
    with TestClient(create_app(container)) as client:
        assert client.get("/api/health").json()["llm_configured"] is False  # app still starts
        response = client.post("/api/chat", json={"question": "Hello?"})

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "llm_not_configured"
    assert "GEMINI_API_KEY" in error["message"]


def test_chat_is_rate_limited(container: AppContainer) -> None:
    container.settings.chat_rate_limit_per_minute = 2
    container.__post_init__()  # rebuild the limiter with the new limit
    with TestClient(create_app(container)) as client:
        codes = [client.post("/api/chat", json={"question": "hi"}).status_code for _ in range(3)]
        last = client.post("/api/chat", json={"question": "hi"})

    assert codes == [200, 200, 429]
    assert last.json()["error"]["code"] == "rate_limited"
    assert int(last.headers["retry-after"]) >= 1
