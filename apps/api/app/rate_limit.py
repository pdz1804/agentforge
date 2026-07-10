"""In-process per-IP token-bucket rate limiting for the expensive endpoints
(`/api/runs`, `/api/eval`, `/api/sandbox/exec`) — PRD Phase 11 hardening.

A single-process token bucket per (endpoint, client IP) is enough for this
app's deployment shape (one API instance behind the demo/e2e); a shared store
(Redis etc.) would be premature infra for a limiter whose only job here is to
blunt accidental hot loops / basic abuse, not survive multi-instance scaling.

Defaults are generous on purpose so normal interactive use and the existing
test/e2e suites (which never set the override envs) are unaffected; override
per-endpoint via `AGENTFORGE_RATE_LIMIT_<NAME>_PER_MIN`.
"""
from __future__ import annotations

import os
import time

from fastapi import HTTPException, Request

_DEFAULT_LIMITS_PER_MINUTE = {"runs": 60, "eval": 30, "sandbox": 30}


class _TokenBucket:
    """Classic token bucket: refills continuously at `capacity` tokens/min,
    holds at most `capacity` tokens, one token spent per allowed request."""

    __slots__ = ("capacity", "refill_per_sec", "tokens", "updated_at")

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.refill_per_sec = capacity / 60.0
        self.tokens = float(capacity)
        self.updated_at = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.updated_at
        self.updated_at = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


# (bucket_name, client_ip) -> bucket. Process-local; reset between test runs
# via reset_rate_limits() so one test's traffic never bleeds into another's.
_buckets: dict[tuple[str, str], _TokenBucket] = {}

# Bound the table so a long-lived process facing many distinct client IPs
# can't grow it without limit. When exceeded, drop buckets untouched for a
# full refill window (>60s) — those have refilled to capacity and are
# indistinguishable from a fresh bucket, so forgetting them changes nothing.
_MAX_TRACKED_BUCKETS = 10_000
_IDLE_EVICT_SECONDS = 60.0


def reset_rate_limits() -> None:
    """Test hook: clear all rate-limit state."""
    _buckets.clear()


def _evict_idle() -> None:
    now = time.monotonic()
    for key in [k for k, b in _buckets.items() if now - b.updated_at > _IDLE_EVICT_SECONDS]:
        del _buckets[key]


def _limit_for(name: str) -> int:
    env_var = f"AGENTFORGE_RATE_LIMIT_{name.upper()}_PER_MIN"
    raw = os.environ.get(env_var)
    default = _DEFAULT_LIMITS_PER_MINUTE[name]
    if raw is None:
        return default
    # A non-numeric or non-positive override must not 500 every request on the
    # hot path — fall back to the safe default instead.
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _make_dependency(name: str):
    async def _check(request: Request) -> None:
        limit = _limit_for(name)
        key = (name, _client_ip(request))
        bucket = _buckets.get(key)
        # A changed env-configured limit (or a first hit) (re)creates the
        # bucket at full capacity for that new limit.
        if bucket is None or bucket.capacity != limit:
            if bucket is None and len(_buckets) >= _MAX_TRACKED_BUCKETS:
                _evict_idle()
            bucket = _TokenBucket(capacity=limit)
            _buckets[key] = bucket
        if not bucket.allow():
            raise HTTPException(status_code=429, detail="rate limit exceeded, try again shortly")

    return _check


# One dependency per protected, expensive endpoint.
runs_rate_limit = _make_dependency("runs")
eval_rate_limit = _make_dependency("eval")
sandbox_rate_limit = _make_dependency("sandbox")
