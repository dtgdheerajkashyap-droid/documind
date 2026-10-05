import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import RateLimitError
from app.core.rate_limit import SlidingWindowRateLimiter


def test_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP"):
        Settings(_env_file=None, chunk_size=200, chunk_overlap=200)


def test_blank_api_key_means_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "  ")
    assert Settings(_env_file=None).gemini_api_key is None


def test_cors_origins_are_comma_separated() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a.test, http://b.test,")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_rate_limiter_blocks_after_limit_per_key() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    limiter.check("a")
    limiter.check("a")
    limiter.check("b")  # separate budget
    with pytest.raises(RateLimitError):
        limiter.check("a")


def test_rate_limiter_zero_disables() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=0)
    for _ in range(100):
        limiter.check("a")
