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
    def __init__(
        self, max_requests: int, window_seconds: float = 60.0, *, what: str = "requests"
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.what = what
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
                    f"Rate limit exceeded: at most {self.max_requests} {self.what} per minute.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory: drop idle keys
                for idle in [k for k, v in self._hits.items() if not v]:
                    del self._hits[idle]


def client_key(request: Request, trusted_proxy_hops: int = 0) -> str:
    """Identify the caller for rate limiting.

    X-Forwarded-For is a client-controlled header, so it is only used when the
    API runs behind `trusted_proxy_hops` known proxies. Each proxy appends the
    address it saw, so the real client is that many entries from the right;
    anything further left could have been forged.
    """
    if trusted_proxy_hops > 0:
        forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        forwarded = [h for h in forwarded if h]
        if len(forwarded) >= trusted_proxy_hops:
            return forwarded[-trusted_proxy_hops]
    return request.client.host if request.client else "unknown"
