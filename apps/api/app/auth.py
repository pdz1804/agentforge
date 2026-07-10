"""Opt-in API-key auth for sensitive endpoints (PRD Phase 11 hardening).

When `AGENTFORGE_API_KEY` is unset (the default — local demo, existing
tests/e2e), `require_api_key` is a no-op: every endpoint stays exactly as
open as it is today. When set, it requires a matching key on whichever
endpoints declare it as a dependency, via either an `X-API-Key` header or an
`Authorization: Bearer <key>` header — a missing/incorrect key gets a 401.

Read-only public endpoints (health, tool list, manifest validation, suite
list) intentionally do NOT depend on this and stay open regardless of the
env var, per the hardening scope.
"""
from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


def _configured_api_key() -> str | None:
    # Read the env live (not cached at import time) so tests can toggle
    # AGENTFORGE_API_KEY per-test via monkeypatch.setenv without reloading the
    # app/module, and so an operator can rotate the key with a process env
    # change + restart rather than a code change.
    key = os.environ.get("AGENTFORGE_API_KEY", "")
    return key or None


def _extract_presented_key(request: Request) -> str | None:
    header_key = request.headers.get("X-API-Key")
    if header_key:
        return header_key
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[len("Bearer ") :].strip() or None
    return None


async def require_api_key(request: Request) -> None:
    """FastAPI dependency: enforces `AGENTFORGE_API_KEY` when one is configured.

    No-op when the env var is unset, so the local demo and existing tests
    (which never set it) keep working unchanged. Uses a constant-time compare
    to avoid leaking key material through response-timing differences.
    """
    expected = _configured_api_key()
    if expected is None:
        return
    presented = _extract_presented_key(request)
    # Compare as bytes: hmac.compare_digest raises TypeError on non-ASCII str
    # (Starlette decodes headers as latin-1), which would surface as a 500
    # instead of a clean 401 for a malformed key.
    if presented is None or not hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="missing or invalid API key")
