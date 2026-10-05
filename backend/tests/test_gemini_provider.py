"""Retry and fallback behaviour of the Gemini provider, using a fake SDK client."""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.errors import LLMNotConfiguredError, LLMProviderError
from app.providers.llm.gemini import GeminiProvider, is_transient


class FakeApiError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"{code} error")
        self.code = code


class FakeModels:
    """Each call pops the next scripted outcome for that model: an exception or a reply."""

    def __init__(self, script: dict[str, list]) -> None:
        self.script = script
        self.calls: list[str] = []

    def _next(self, model: str):
        self.calls.append(model)
        outcome = self.script[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def generate_content(self, *, model: str, contents: str, config) -> SimpleNamespace:
        return SimpleNamespace(text=self._next(model))

    async def generate_content_stream(self, *, model: str, contents: str, config):
        outcome = self._next(model)

        async def chunks():
            for piece in outcome:
                if isinstance(piece, Exception):
                    raise piece
                yield SimpleNamespace(text=piece)

        return chunks()


def make_provider(script: dict[str, list], **kwargs) -> tuple[GeminiProvider, FakeModels]:
    provider = GeminiProvider(
        "key",
        "primary",
        fallback_models=["backup"],
        retry_base_delay=0,
        **kwargs,
    )
    models = FakeModels(script)
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return provider, models


def collect(provider: GeminiProvider) -> list[str]:
    async def run() -> list[str]:
        return [text async for text in provider.stream("prompt")]

    return asyncio.run(run())


def test_transient_classification() -> None:
    assert is_transient(FakeApiError(503))
    assert is_transient(FakeApiError(429))
    assert is_transient(TimeoutError())
    assert not is_transient(FakeApiError(400))
    assert not is_transient(ValueError("bad"))


def test_retries_transient_errors_then_succeeds() -> None:
    provider, models = make_provider({"primary": [FakeApiError(503), "hello"]})
    assert asyncio.run(provider.generate("prompt")) == "hello"
    assert models.calls == ["primary", "primary"]


def test_falls_back_to_next_model_after_retries() -> None:
    provider, models = make_provider(
        {"primary": [FakeApiError(503)] * 3, "backup": ["from backup"]}, max_retries=2
    )
    assert asyncio.run(provider.generate("prompt")) == "from backup"
    assert models.calls == ["primary", "primary", "primary", "backup"]


def test_non_transient_error_fails_fast() -> None:
    provider, models = make_provider({"primary": [FakeApiError(400)]})
    with pytest.raises(LLMProviderError, match="Gemini request failed"):
        asyncio.run(provider.generate("prompt"))
    assert models.calls == ["primary"]


def test_gives_up_with_friendly_message_when_everything_is_overloaded() -> None:
    provider, _ = make_provider(
        {"primary": [FakeApiError(503)] * 2, "backup": [FakeApiError(503)] * 2}, max_retries=1
    )
    with pytest.raises(LLMProviderError, match="temporarily overloaded"):
        asyncio.run(provider.generate("prompt"))


def test_stream_retries_before_first_token() -> None:
    provider, models = make_provider(
        {"primary": [[FakeApiError(503)], ["Hel", "lo"]]}  # fails on first chunk, then works
    )
    assert collect(provider) == ["Hel", "lo"]
    assert models.calls == ["primary", "primary"]


def test_stream_does_not_retry_after_text_was_sent() -> None:
    provider, models = make_provider({"primary": [["Partial", FakeApiError(503)]]})

    received: list[str] = []

    async def run() -> None:
        async for text in provider.stream("prompt"):
            received.append(text)

    with pytest.raises(LLMProviderError):
        asyncio.run(run())
    assert received == ["Partial"]  # no duplicated text from a retry
    assert models.calls == ["primary"]


def test_missing_key_is_not_retried() -> None:
    provider = GeminiProvider(None, "primary")
    with pytest.raises(LLMNotConfiguredError, match="GEMINI_API_KEY"):
        asyncio.run(provider.generate("prompt"))
