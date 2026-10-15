"""TradeSathi AI — In-Application Defense-in-Depth Rate Limiter
Provides thread-safe sliding-window in-memory throttling for sensitive authentication
and portal endpoints. Operates as defense-in-depth alongside reverse-proxy rate limiting.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter per client IP."""

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60,
        name: str = "default",
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name
        self._lock = threading.Lock()
        self._history: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def _cleanup(self, now: float) -> None:
        """Periodically prune stale IP buckets to bound memory usage."""
        if now - self._last_cleanup > 300:
            threshold = now - self.window_seconds
            for key, timestamps in list(self._history.items()):
                valid = [t for t in timestamps if t > threshold]
                if valid:
                    self._history[key] = valid
                else:
                    del self._history[key]
            self._last_cleanup = now

    def check(self, identifier: str) -> tuple[bool, int]:
        """Check if request is allowed for identifier. Returns (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            self._cleanup(now)
            threshold = now - self.window_seconds
            valid_timestamps = [t for t in self._history[identifier] if t > threshold]
            self._history[identifier] = valid_timestamps

            if len(valid_timestamps) >= self.max_requests:
                oldest = valid_timestamps[0]
                retry_after = max(1, int(oldest + self.window_seconds - now))
                return False, retry_after

            self._history[identifier].append(now)
            return True, 0

    def reset(self) -> None:
        """Reset internal rate limit tracking state (primarily for test harnesses)."""
        with self._lock:
            self._history.clear()
            self._last_cleanup = time.time()

    def __call__(self, request: Request) -> None:
        """FastAPI dependency callable."""
        # 1. Configurable bypass for test environments
        if os.getenv("RATE_LIMITING_ENABLED", "1").lower() in ("0", "false", "no"):
            return
        if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("TRADESATHI_TEST_MODE") == "1":
            return

        # 2. Extract client IP safely respecting trusted proxies
        trusted_proxies = {
            ip.strip()
            for ip in os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1").split(",")
            if ip.strip()
        }
        client_ip = request.client.host if request.client else "unknown"
        if client_ip in trusted_proxies:
            x_forwarded = request.headers.get("x-forwarded-for")
            if x_forwarded:
                client_ip = x_forwarded.split(",")[0].strip()

        # 3. Check rate limit
        allowed, retry_after = self.check(client_ip)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {self.name}. Please wait {retry_after}s before retrying.",
                headers={"Retry-After": str(retry_after)},
            )


# Pre-configured singletons for sensitive authentication and portal endpoints
auth_rate_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("RATE_LIMIT_AUTH_MAX", "10")),
    window_seconds=int(os.getenv("RATE_LIMIT_AUTH_WINDOW", "60")),
    name="authentication",
)

invitation_rate_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("RATE_LIMIT_INVITE_MAX", "10")),
    window_seconds=int(os.getenv("RATE_LIMIT_INVITE_WINDOW", "60")),
    name="invitation_acceptance",
)
