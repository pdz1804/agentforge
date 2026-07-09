"""API-layer coverage for endpoints not exercised elsewhere: `/api/sandbox/exec`
and `/api/index`, plus edge cases of `/api/memory` and `/api/runs` beyond the
happy paths already covered in test_health.py. All offline except the sandbox
happy-path test, which is skipped automatically when Docker is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from agent_core import EmbeddingSearchTool, InMemoryVectorStore

from app.main import app
from app.main import registries as app_registries

client = TestClient(app)


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# /api/sandbox/exec
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _docker_available(), reason="docker not available")
def test_sandbox_exec_happy_path_runs_real_container():
    resp = client.post("/api/sandbox/exec", json={"code": "print(2 + 2)"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["exit_code"] == 0
    assert body["stdout"].strip() == "4"
    assert body["timed_out"] is False


def test_sandbox_exec_falls_back_when_sandbox_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    # Offline, regardless of whether Docker is installed: force the executor
    # to fail the way it would if the docker CLI/daemon were unreachable, and
    # confirm the endpoint degrades to its documented fallback response
    # rather than a 500.
    from agent_core import DockerCodeExecutor

    async def boom(self, code: str, ctx):
        raise RuntimeError("docker unreachable")

    monkeypatch.setattr(DockerCodeExecutor, "run", boom)

    resp = client.post("/api/sandbox/exec", json={"code": "print(1)"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["exit_code"] == 1
    assert body["stderr"] == "sandbox unavailable"
    assert body["timed_out"] is False


def test_sandbox_exec_timeout_out_of_range_is_422():
    resp = client.post("/api/sandbox/exec", json={"code": "print(1)", "timeout_s": 999})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# /api/index
# --------------------------------------------------------------------------- #
def test_index_document_without_api_key_returns_400(monkeypatch: pytest.MonkeyPatch):
    # The default embedding_search tool uses the live openai_embed fn, which
    # needs OPENAI_API_KEY. Force it absent so the offline failure path is
    # exercised deterministically regardless of the host environment.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = client.post("/api/index", json={"doc_id": "d1", "text": "the rose is red"})
    assert resp.status_code == 400
    assert "OPENAI_API_KEY" in resp.json()["detail"]


def test_index_document_succeeds_with_fake_embedder():
    # Swap in a deterministic fake-embedder tool for this test only, so
    # indexing succeeds without any network call, then restore the original.
    original = app_registries.tools.get("embedding_search")

    async def fake_embed(text: str) -> list[float]:
        return [float(len(text)), 0.0]

    app_registries.tools.register(
        "embedding_search", EmbeddingSearchTool(InMemoryVectorStore(), fake_embed), overwrite=True
    )
    try:
        resp = client.post("/api/index", json={"doc_id": "d1", "text": "the rose is red"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "doc_id": "d1"}
    finally:
        app_registries.tools.register("embedding_search", original, overwrite=True)


# --------------------------------------------------------------------------- #
# /api/memory — edge cases beyond the add/list/delete happy path
# --------------------------------------------------------------------------- #
def test_memory_api_query_param_searches_instead_of_listing_all():
    client.post("/api/memory", json={"text": "loves the rose", "namespace": "searchtest"})
    client.post("/api/memory", json={"text": "lives in Hanoi", "namespace": "searchtest"})

    resp = client.get("/api/memory", params={"namespace": "searchtest", "query": "rose"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items and all("rose" in i["text"] for i in items)


def test_memory_api_delete_unknown_id_is_a_no_op():
    # Deleting an id that was never added must not error (idempotent delete).
    resp = client.delete("/api/memory", params={"id": "does-not-exist", "namespace": "searchtest"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# --------------------------------------------------------------------------- #
# /api/runs — edge cases beyond the persist/list/get/export happy path
# --------------------------------------------------------------------------- #
def test_runs_list_respects_limit_param():
    for i in range(3):
        client.post(
            "/api/runs",
            json={
                "manifest": {
                    "id": "runner",
                    "model": {"provider": "echo", "name": "test-model"},
                    "prompt_ref": "prompts/echo_agent.md",
                    "tools": [],
                },
                "input": f"limit test {i}",
            },
        )
    resp = client.get("/api/runs", params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) == 1


def test_runs_export_unknown_is_404():
    resp = client.get("/api/runs/does-not-exist/export")
    assert resp.status_code == 404
