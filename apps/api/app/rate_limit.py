"""In-process rate limiting.

Deliberately simple: a token bucket per key, held in a dict. This is correct for
a single-process deployment, which is what the compose file describes (one API
container). Running multiple API replicas would require a shared store; that is
documented rather than silently mis-implemented.

Two buckets are used:
  * ``login`` — per account+IP, tiny budget, to blunt credential stuffing.
  * ``api``   — per user or IP, generous, to blunt scraping and accidental loops.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    updated: float = field(default_factory=time.monotonic)


class RateLimiter:
    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = float(capacity)
        self.refill = float(refill_per_second)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def _sweep(self, now: float) -> None:
        # Bound memory: drop buckets that have been idle long enough to be full.
        if now - self._last_sweep < 300:
            return
        stale = [
            key
            for key, bucket in self._buckets.items()
            if (self.capacity - bucket.tokens) / self.refill < 600 and now - bucket.updated > 600
        ]
        for key in stale:
            self._buckets.pop(key, None)
        self._last_sweep = now

    def take(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Consume ``cost`` tokens. Returns ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity)
                self._buckets[key] = bucket
            elapsed = now - bucket.updated
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill)
            bucket.updated = now
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True, 0.0
            deficit = cost - bucket.tokens
            return False, round(deficit / self.refill, 2) if self.refill else 60.0

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)


# Login: 8 attempts per 5 minutes, refilling slowly.
login_limiter = RateLimiter(capacity=8, refill_per_second=8 / 300)
# Registration: 5 per hour per IP.
register_limiter = RateLimiter(capacity=5, refill_per_second=5 / 3600)
# General API: 120 requests per minute.
api_limiter = RateLimiter(capacity=120, refill_per_second=2.0)
# Expensive operations (job start, evaluate): 10 per minute.
heavy_limiter = RateLimiter(capacity=10, refill_per_second=10 / 60)
# Demo entry: each attempt makes the server open an outbound connection, so the
# budget is tight — 6 per 10 minutes per IP. A genuine visitor needs one.
join_limiter = RateLimiter(capacity=6, refill_per_second=6 / 600)