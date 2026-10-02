"""
In-memory rate limiting — used to slow down password guessing on the login endpoint.
In-memory is enough for a single Railway instance; it resets on restart.

Limits are kept per client IP and, for sign-in, per account too: the IP comes from the
X-Forwarded-For header, which a client can add values to before Railway's proxy appends its
own, so an attacker rotating fake addresses is still stopped by the account's limit.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import get_settings

MAX_KEYS = 10_000  # past this many, keys with no hit left in the window are forgotten


class RateLimiter:
    """Sliding-window counter: at most `limit` hits per `window_seconds` per key."""

    def __init__(self, window_seconds: int) -> None:
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                self._forget_idle(now)
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def _forget_idle(self, now: float) -> None:
        # A key's newest hit is its last one: once that is out of the window, so is the key.
        # (Checking for empty queues only would keep every address seen once, forever.)
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
            del self._hits[key]


_limiters: dict[str, RateLimiter] = {}


def client_ip(request: Request) -> str:
    # Behind Railway's proxy this is the address from X-Forwarded-For, because uvicorn
    # runs with --proxy-headers (see Dockerfile). Not proof of identity: see the module note.
    return request.client.host if request.client else "unknown"


def check(name: str, key: str, limit: int, window_seconds: int) -> None:
    """Count one hit for `key` under the `name` limiter; 429 once it is over `limit`."""
    limiter = _limiters.setdefault(name, RateLimiter(window_seconds))
    if not limiter.hit(key, limit):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="طلبات كثيرة، حاول مرة أخرى بعد قليل",
            headers={"Retry-After": str(window_seconds)},
        )


def rate_limited(name: str, setting: str, window_seconds: int = 60):
    """Dependency factory: limit per client IP, read from Settings.<setting> on each request."""

    def dependency(request: Request) -> None:
        check(name, client_ip(request), getattr(get_settings(), setting), window_seconds)

    return dependency


def reset_rate_limits() -> None:
    """Clear all counters (used by tests)."""
    _limiters.clear()
