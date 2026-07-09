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


def reset_rate_limits() -> None:
    """Test hook: clear all rate-limit state."""
    _buckets.clear()


def _limit_for(name: str) -> int:
    env_var = f"AGENTFORGE_RATE_LIMIT_{name.upper()}_PER_MIN"
    return int(os.environ.get(env_var, _DEFAULT_LIMITS_PER_MINUTE[name]))


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
            bucket = _TokenBucket(capacity=limit)
            _buckets[key] = bucket
        if not bucket.allow():
            raise HTTPException(status_code=429, detail="rate limit exceeded, try again shortly")

    return _check


# One dependency per protected, expensive endpoint.
runs_rate_limit = _make_dependency("runs")
eval_rate_limit = _make_dependency("eval")
sandbox_rate_limit = _make_dependency("sandbox")
