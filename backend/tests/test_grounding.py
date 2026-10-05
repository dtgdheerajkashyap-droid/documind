"""Grounding and refusal behaviour of the chat pipeline, with a mocked LLM."""

import asyncio
from pathlib import Path

import pytest

from app.core.config import REFUSAL_MESSAGE
from app.core.container import AppContainer
from app.core.errors import LLMProviderError
from app.core.workspace import DEFAULT_WORKSPACE_ID
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatEvent, build_citations
from app.services.prompts import (
    ANSWER_SYSTEM_PROMPT,
    build_answer_prompt,
    cited_indices,
    clean_rewritten_query,
    is_refusal,
)
from app.services.retrieval import RetrievedChunk
from tests.conftest import ingest_document
from tests.fakes import FakeLLM


def _run(container: AppContainer, question: str, **kwargs) -> list[ChatEvent]:
    async def collect() -> list[ChatEvent]:
        request = ChatRequest(question=question, **kwargs)
        return [e async for e in container.chat_service.stream(request, DEFAULT_WORKSPACE_ID)]

    return asyncio.run(collect())


def _answer(events: list[ChatEvent]) -> dict:
    return next(e.data for e in events if e.event == "done")


def _chunk(i: int, text: str = "text") -> RetrievedChunk:
    return RetrievedChunk(f"c{i}", "d1", "doc.pdf", i, i, text, 0.9 - i / 100)


# --- Pure helpers ----------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        REFUSAL_MESSAGE,
        "I couldn’t find this in your documents.",
        "  i couldn't find this in your documents  ",
        "I couldn't find this in your documents. The sources only cover refunds.",
    ],
)
def test_is_refusal_detects_variants(answer: str) -> None:
    assert is_refusal(answer)


def test_is_refusal_ignores_real_answers() -> None:
    assert not is_refusal("Refunds are available within 30 days [1].")


def test_cited_indices_are_deduplicated_and_bounded() -> None:
    assert cited_indices("A [2]. B [1][2]. C [9].", max_index=3) == [2, 1]


def test_build_citations_keeps_prompt_numbering() -> None:
    chunks = [_chunk(1), _chunk(2), _chunk(3)]
    citations = build_citations("Answer [3] and [1].", chunks)
    assert [(c.index, c.chunk_id) for c in citations] == [(1, "c1"), (3, "c3")]


def test_build_citations_falls_back_to_all_sources() -> None:
    citations = build_citations("Answer without markers.", [_chunk(1), _chunk(2)])
    assert [c.index for c in citations] == [1, 2]


def test_answer_prompt_numbers_sources_and_states_rules() -> None:
    prompt = build_answer_prompt("Q?", [_chunk(1, "alpha"), _chunk(2, "beta")])
    assert "[1] (file: doc.pdf, page 1)\nalpha" in prompt
    assert "[2] (file: doc.pdf, page 2)\nbeta" in prompt
    assert prompt.endswith("QUESTION: Q?\n\nANSWER:")
    assert REFUSAL_MESSAGE in ANSWER_SYSTEM_PROMPT
    assert "ONLY" in ANSWER_SYSTEM_PROMPT


def test_clean_rewritten_query() -> None:
    assert clean_rewritten_query('"Standalone question: What is X?"', "orig") == "What is X?"
    assert clean_rewritten_query("   ", "orig") == "orig"


# --- Pipeline behaviour ----------------------------------------------------


def test_refuses_without_calling_llm_when_retrieval_is_weak(
    container: AppContainer, fake_llm: FakeLLM, sample_pdf: Path
) -> None:
    ingest_document(container, sample_pdf)

    events = _run(container, "Explain quantum chromodynamics gluon lattice theory")

    done = _answer(events)
    assert done["answer"] == REFUSAL_MESSAGE
    assert done["refused"] is True
    assert fake_llm.calls == []  # the gate stopped us before generation
    citations = next(e.data for e in events if e.event == "citations")
    assert citations == {"citations": []}


def test_refuses_when_no_documents_exist(container: AppContainer, fake_llm: FakeLLM) -> None:
    events = _run(container, "What is the refund policy?")
    assert _answer(events)["answer"] == REFUSAL_MESSAGE
    assert fake_llm.calls == []


def test_llm_refusal_is_normalised_and_has_no_citations(
    container: AppContainer, fake_llm: FakeLLM, sample_pdf: Path
) -> None:
    ingest_document(container, sample_pdf)
    fake_llm.responder = lambda prompt, system: "I couldn’t find this in your documents!"

    done = _answer(_run(container, "What is the refund policy for coffee bags?"))

    assert done["answer"] == REFUSAL_MESSAGE
    assert done["refused"] is True


def test_grounded_answer_streams_tokens_and_cites_sources(
    container: AppContainer, fake_llm: FakeLLM, sample_pdf: Path
) -> None:
    ingest_document(container, sample_pdf)
    fake_llm.responder = lambda prompt, system: "Unopened bags can be returned within 30 days [1]."

    events = _run(container, "What is the refund policy for unopened coffee bags?")

    names = [e.event for e in events]
    assert names[0] == "meta"
    assert names[-2:] == ["citations", "done"]
    streamed = "".join(e.data["text"] for e in events if e.event == "token")
    assert streamed == "Unopened bags can be returned within 30 days [1]."

    citations = next(e.data["citations"] for e in events if e.event == "citations")
    assert len(citations) == 1
    assert citations[0]["index"] == 1
    assert citations[0]["page"] == 2
    assert "30 days" in citations[0]["text"]

    prompt, system = fake_llm.calls[-1]
    assert system == ANSWER_SYSTEM_PROMPT
    assert "Customers may return unopened bags" in prompt


def test_follow_up_question_is_rewritten_with_history(
    container: AppContainer, fake_llm: FakeLLM, sample_pdf: Path
) -> None:
    ingest_document(container, sample_pdf)

    def responder(prompt: str, system: str | None) -> str:
        if "FOLLOW-UP QUESTION" in prompt:
            return "How many vacation days do full-time baristas get?"
        return "They receive 20 days of paid vacation [1]."

    fake_llm.responder = responder
    first = _answer(_run(container, "What benefits do baristas receive?"))

    events = _run(container, "How many days is that?", session_id=first["session_id"])

    meta = events[0].data
    assert meta["standalone_query"] == "How many vacation days do full-time baristas get?"
    rewrite_prompt = next(p for p, _ in fake_llm.calls if "FOLLOW-UP QUESTION" in p)
    assert "What benefits do baristas receive?" in rewrite_prompt  # history was included
    citations = next(e.data["citations"] for e in events if e.event == "citations")
    assert citations[0]["page"] == 3


def test_rewrite_failure_falls_back_to_original_question(
    container: AppContainer, fake_llm: FakeLLM, sample_pdf: Path
) -> None:
    ingest_document(container, sample_pdf)
    first = _answer(_run(container, "What is the refund policy?"))

    async def failing_generate(prompt: str, *, system: str | None = None) -> str:
        raise LLMProviderError("boom")

    fake_llm.generate = failing_generate  # type: ignore[method-assign]
    events = _run(container, "And for opened bags?", session_id=first["session_id"])

    assert events[0].data["standalone_query"] == "And for opened bags?"
    assert events[-1].event == "done"


def test_llm_error_mid_stream_emits_error_event(
    container: AppContainer, fake_llm: FakeLLM, sample_pdf: Path
) -> None:
    ingest_document(container, sample_pdf)

    async def broken_stream(prompt: str, *, system: str | None = None):
        yield "Partial"
        raise LLMProviderError("Gemini request failed: quota exceeded")

    fake_llm.stream = broken_stream  # type: ignore[method-assign]
    events = _run(container, "What is the refund policy for coffee?")

    assert events[-1].event == "error"
    assert events[-1].data["code"] == "llm_error"
    assert "quota" in events[-1].data["message"]
