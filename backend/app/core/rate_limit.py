"""A small in-memory sliding-window rate limiter.

Good enough for a single-process deployment. With multiple replicas this would
move to Redis (see README, "Future improvements").
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import RateLimitError


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record a hit for `key`, raising RateLimitError if the limit is exceeded."""
        if self.max_requests <= 0:  # 0 disables rate limiting
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                retry_after = max(1, int(self.window_seconds - (now - hits[0])) + 1)
                raise RateLimitError(
                    f"Rate limit exceeded: at most {self.max_requests} chat requests per minute.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)


def client_key(request: Request) -> str:
    """Identify the caller. Uses the first X-Forwarded-For hop when behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
