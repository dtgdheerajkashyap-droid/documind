from fastapi.testclient import TestClient

from tests.conftest import parse_sse


def _start_session(client: TestClient, question: str) -> str:
    events = parse_sse(client.post("/api/chat", json={"question": question}).text)
    return events[0][1]["session_id"]


def test_list_sessions_most_recent_first(client: TestClient) -> None:
    first = _start_session(client, "First question")
    second = _start_session(client, "Second question")

    sessions = client.get("/api/sessions").json()

    assert [s["id"] for s in sessions] == [second, first]
    assert sessions[0]["title"] == "Second question"
    assert sessions[0]["message_count"] == 2


def test_long_question_titles_are_truncated(client: TestClient) -> None:
    session_id = _start_session(client, "word " * 50)
    title = client.get(f"/api/sessions/{session_id}").json()["title"]
    assert len(title) <= 80
    assert title.endswith("...")


def test_delete_session(client: TestClient) -> None:
    session_id = _start_session(client, "Temporary")

    assert client.delete(f"/api/sessions/{session_id}").status_code == 204
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert client.get("/api/sessions").json() == []
    assert client.delete(f"/api/sessions/{session_id}").status_code == 404


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["vector_store"] is True
    assert body["llm_configured"] is True
    assert response.headers["x-request-id"]


def test_unknown_route_uses_error_format(client: TestClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
