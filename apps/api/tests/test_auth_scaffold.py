"""Per-user auth SCAFFOLD tests (backend only — no login UI/OAuth this round).

Auth OFF (the default: `AGENTFORGE_JWT_SECRET` unset) must leave every
existing single-user flow byte-for-byte unchanged — `resolve_user` always
resolves to `DEFAULT_USER` ("public"), the same owner every store row
already defaults to. Auth ON (`AGENTFORGE_JWT_SECRET` set) turns on real
per-user isolation gated by a bearer JWT; the isolation tests here prove one
user's runs/manifests are invisible to (and unfetchable by) another.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.auth import DEFAULT_USER, issue_token
from app.main import app

client = TestClient(app)


def _echo_run_body(input_text: str = "hi") -> dict:
    return {
        "manifest": {
            "id": "auth_scaffold_runner",
            "model": {"provider": "echo", "name": "test-model"},
            "prompt_ref": "prompts/echo_agent.md",
            "tools": [],
        },
        "input": input_text,
    }


def _manifest(manifest_id: str) -> dict:
    return {
        "id": manifest_id,
        "model": {"provider": "echo", "name": "test-model"},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": [],
    }


def _run_id_from_sse(resp) -> str:
    return json.loads(resp.text.splitlines()[0].removeprefix("data: "))["run_id"]


def _token_for(user_id: str) -> str:
    # Mint directly (the JWT secret is set by the caller). The /api/auth/token
    # endpoint additionally requires the shared API key to be configured
    # (fail-closed), which is exercised separately below; the isolation tests
    # only need a valid token for a user, not the HTTP mint path.
    return issue_token(user_id)


def _auth_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {_token_for(user_id)}"}


# --------------------------------------------------------------------------- #
# Auth OFF (default): unchanged single-user behavior.
# --------------------------------------------------------------------------- #
def test_resolve_user_defaults_to_public_when_secret_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "public"}


def test_token_mint_is_501_when_secret_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)
    resp = client.post("/api/auth/token", json={"user_id": "alice"})
    assert resp.status_code == 501


def test_existing_run_flow_works_without_a_token_when_auth_off(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)
    run_resp = client.post("/api/runs", json=_echo_run_body("no token needed"))
    assert run_resp.status_code == 200
    run_id = _run_id_from_sse(run_resp)

    listed = client.get("/api/runs").json()["runs"]
    assert any(r["id"] == run_id for r in listed)

    got = client.get(f"/api/runs/{run_id}")
    assert got.status_code == 200


def test_existing_manifest_flow_works_without_a_token_when_auth_off(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)
    mid = "auth_off_manifest"
    created = client.post("/api/agents", json={"manifest": _manifest(mid)})
    assert created.status_code == 200

    got = client.get(f"/api/agents/{mid}")
    assert got.status_code == 200
    assert got.json()["owner"] == "public"


# --------------------------------------------------------------------------- #
# Auth ON: token issuance, 401s, per-user isolation.
# --------------------------------------------------------------------------- #
def test_issue_token_round_trips_through_resolve_user(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_JWT_SECRET", "test-scaffold-secret")
    # Minting also requires the shared API key (fail-closed), so set + present it.
    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        minted = client.post(
            "/api/auth/token", json={"user_id": "alice"}, headers={"X-API-Key": "s3cret-key"}
        )
        assert minted.status_code == 200
        body = minted.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

        me = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert me.status_code == 200
        assert me.json() == {"user_id": "alice"}
    finally:
        monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


def test_token_mint_fails_closed_when_jwt_on_but_no_api_key(monkeypatch: pytest.MonkeyPatch):
    # JWT auth ON without a shared API key would make minting fully open; the
    # endpoint must refuse (503) rather than issue unauthenticated tokens.
    monkeypatch.setenv("AGENTFORGE_JWT_SECRET", "test-scaffold-secret")
    monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)
    try:
        resp = client.post("/api/auth/token", json={"user_id": "alice"})
        assert resp.status_code == 503
    finally:
        monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)


def test_public_sentinel_and_unsafe_user_ids_are_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_JWT_SECRET", "test-scaffold-secret")
    try:
        for bad in (DEFAULT_USER, "alice:default", "../x", "a b", ""):
            with pytest.raises(ValueError):
                issue_token(bad)
        # A hand-forged "public" token is rejected at resolve time, so it can
        # never reach the shared default bucket once auth is on.
        import jwt

        forged = jwt.encode({"sub": DEFAULT_USER}, "test-scaffold-secret", algorithm="HS256")
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
        assert me.status_code == 401
    finally:
        monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)


def test_missing_or_invalid_token_is_401_when_secret_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_JWT_SECRET", "test-scaffold-secret")
    try:
        assert client.get("/api/auth/me").status_code == 401
        assert (
            client.get(
                "/api/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"}
            ).status_code
            == 401
        )
        assert client.get("/api/runs").status_code == 401
    finally:
        monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)


def test_token_signed_with_a_different_secret_is_401(monkeypatch: pytest.MonkeyPatch):
    import jwt

    monkeypatch.setenv("AGENTFORGE_JWT_SECRET", "test-scaffold-secret")
    try:
        forged = jwt.encode({"sub": "alice"}, "wrong-secret", algorithm="HS256")
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
        assert resp.status_code == 401
    finally:
        monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)


def test_token_mint_requires_configured_api_key_when_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_JWT_SECRET", "test-scaffold-secret")
    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        no_key = client.post("/api/auth/token", json={"user_id": "alice"})
        assert no_key.status_code == 401

        with_key = client.post(
            "/api/auth/token",
            json={"user_id": "alice"},
            headers={"X-API-Key": "s3cret-key"},
        )
        assert with_key.status_code == 200
    finally:
        monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


def test_run_isolation_between_users(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_JWT_SECRET", "test-scaffold-secret")
    try:
        alice_headers = _auth_header("alice")
        bob_headers = _auth_header("bob")

        run_resp = client.post(
            "/api/runs", json=_echo_run_body("alice's run"), headers=alice_headers
        )
        assert run_resp.status_code == 200
        run_id = _run_id_from_sse(run_resp)

        # Alice's run must not appear in bob's list.
        bob_list = client.get("/api/runs", headers=bob_headers).json()["runs"]
        assert all(r["id"] != run_id for r in bob_list)

        # Bob fetching alice's run id directly gets a 404 (not a 403 — no
        # existence leak), same for the export endpoint.
        assert client.get(f"/api/runs/{run_id}", headers=bob_headers).status_code == 404
        assert client.get(f"/api/runs/{run_id}/export", headers=bob_headers).status_code == 404

        # Alice can fetch her own run.
        own = client.get(f"/api/runs/{run_id}", headers=alice_headers)
        assert own.status_code == 200
        assert own.json()["owner"] == "alice"
    finally:
        monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)


def test_manifest_isolation_between_users(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_JWT_SECRET", "test-scaffold-secret")
    try:
        alice_headers = _auth_header("alice")
        bob_headers = _auth_header("bob")
        mid = "auth_scaffold_isolated_manifest"

        created = client.post(
            "/api/agents", json={"manifest": _manifest(mid)}, headers=alice_headers
        )
        assert created.status_code == 200
        assert created.json()["owner"] == "alice"

        # Bob's listing must not include alice's manifest id.
        bob_agents = client.get("/api/agents", headers=bob_headers).json()["agents"]
        assert all(a["id"] != mid for a in bob_agents)

        # Bob fetching it directly (or its version history) gets a 404.
        assert client.get(f"/api/agents/{mid}", headers=bob_headers).status_code == 404
        assert client.get(f"/api/agents/{mid}/versions", headers=bob_headers).status_code == 404

        # Bob cannot hijack alice's manifest id via PUT either.
        hijack = client.put(
            f"/api/agents/{mid}", json={"manifest": _manifest(mid)}, headers=bob_headers
        )
        assert hijack.status_code == 404

        # Alice can still fetch/update her own manifest.
        own = client.get(f"/api/agents/{mid}", headers=alice_headers)
        assert own.status_code == 200
    finally:
        monkeypatch.delenv("AGENTFORGE_JWT_SECRET", raising=False)
