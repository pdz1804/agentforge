"""Opt-in API-key auth for sensitive endpoints (PRD Phase 11 hardening), plus
a per-user auth SCAFFOLD (this phase): JWT-based user resolution + data
isolation, backend only — no login UI, no OAuth. Both mechanisms compose:
`require_api_key` gates *access* (a shared secret), `resolve_user` gates
*whose data* an authenticated caller sees.

When `AGENTFORGE_API_KEY` is unset (the default — local demo, existing
tests/e2e), `require_api_key` is a no-op: every endpoint stays exactly as
open as it is today. When set, it requires a matching key on whichever
endpoints declare it as a dependency, via either an `X-API-Key` header or an
`Authorization: Bearer <key>` header — a missing/incorrect key gets a 401.

Read-only public endpoints (health, tool list, manifest validation, suite
list) intentionally do NOT depend on this and stay open regardless of the
env var, per the hardening scope.

Per-user scaffold: when `AGENTFORGE_JWT_SECRET` is unset (the default),
`resolve_user` always returns `DEFAULT_USER` ("public") — every existing
caller keeps writing to and reading from the same single-user data as
before, byte-for-byte. Setting the secret turns on real per-user isolation:
callers must present a valid `Authorization: Bearer <jwt>` (HS256, `sub`
claim = user id) or get a 401. `issue_token` mints one for dev/testing —
see `POST /api/auth/token` in `main.py` for the caveat that this is a
scaffold endpoint, not a real login/OAuth flow.
"""
from __future__ import annotations

import hmac
import os
import time

from fastapi import HTTPException, Request

# The owner every store row defaults to. Also hardcoded (same literal) inside
# agent_core's stores so they don't need to import this api-layer module —
# keep the two in sync if this ever changes.
DEFAULT_USER = "public"


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


# --------------------------------------------------------------------------- #
# Per-user auth scaffold (backend only — no login UI/OAuth this round).
# --------------------------------------------------------------------------- #
_JWT_ALGORITHM = "HS256"


def _configured_jwt_secret() -> str | None:
    # Read live, like _configured_api_key: lets tests toggle
    # AGENTFORGE_JWT_SECRET per-test via monkeypatch without reloading the app.
    secret = os.environ.get("AGENTFORGE_JWT_SECRET", "")
    return secret or None


def issue_token(user_id: str, expires_in_s: int = 86400) -> str:
    """Mint a dev-scaffold HS256 JWT for ``user_id``. Raises if auth is OFF.

    NOT a real login/OAuth flow — a real identity provider replaces this
    before any of this ships to end users. Kept here only so the isolation
    this phase adds is exercisable/testable without one.
    """
    import jwt  # lazy: agent_core/import-time users never pay the PyJWT cost

    secret = _configured_jwt_secret()
    if secret is None:
        raise RuntimeError("AGENTFORGE_JWT_SECRET is not configured; cannot issue tokens")
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + expires_in_s}
    return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)


async def resolve_user(request: Request) -> str:
    """FastAPI dependency: resolves the calling user id for data scoping.

    `AGENTFORGE_JWT_SECRET` unset (the default) => always `DEFAULT_USER`, so
    every store call scopes to the same single-user bucket every row already
    defaults to — unchanged behavior. Set => requires a valid
    `Authorization: Bearer <jwt>` (HS256, signed with the same secret); a
    missing/invalid/expired token is a 401. Returns the token's `sub` claim.
    """
    secret = _configured_jwt_secret()
    if secret is None:
        return DEFAULT_USER

    import jwt  # lazy: same rationale as issue_token

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth_header[len("Bearer ") :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        payload = jwt.decode(token, secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid or expired token") from exc
    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(status_code=401, detail="token missing 'sub' claim")
    return sub
