"""API smoke tests via Starlette TestClient."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "echo" in body["tools"]
    assert "anthropic" in body["models"]


def test_list_tools():
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    assert "echo" in tools
    assert "embedding_search" in tools  # Phase 3b
    assert "code_executor" in tools


def test_validate_valid_manifest():
    resp = client.post(
        "/api/agents/validate",
        json={
            "manifest": {
                "id": "demo",
                "model": {"provider": "anthropic", "name": "claude-sonnet-5"},
                "prompt_ref": "prompts/echo_agent.md",
                "tools": ["echo"],
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["id"] == "demo"


def test_validate_unknown_tool_returns_error():
    resp = client.post(
        "/api/agents/validate",
        json={
            "manifest": {
                "id": "broken",
                "model": {"provider": "anthropic", "name": "claude-sonnet-5"},
                "prompt_ref": "prompts/echo_agent.md",
                "tools": ["ghost_tool"],
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "ghost_tool" in body["error"]


def test_run_streams_answer():
    # Uses the offline 'echo' model so the API run needs no API key.
    resp = client.post(
        "/api/runs",
        json={
            "manifest": {
                "id": "runner",
                "model": {"provider": "echo", "name": "test-model"},
                "prompt_ref": "prompts/echo_agent.md",
                "tools": [],
            },
            "input": "hello stream",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "data:" in body
    assert "hello stream" in body  # the echoed answer streamed through
    assert '"type": "done"' in body


def test_run_invalid_manifest_streams_error_event():
    resp = client.post(
        "/api/runs",
        json={
            "manifest": {
                "id": "runner",
                "model": {"provider": "echo", "name": "test-model"},
                "prompt_ref": "prompts/echo_agent.md",
                "tools": ["ghost_tool"],
            },
            "input": "x",
        },
    )
    assert resp.status_code == 200
    assert '"type": "error"' in resp.text
    assert "ghost_tool" in resp.text


def test_run_streams_error_event_on_runtime_failure():
    # A provider that fails mid-run must surface a structured error event,
    # not a truncated stream (the streamed-error contract).
    from agent_core import ModelProvider
    from agent_core.errors import AgentCoreError as CoreError

    from app.main import registries as app_registries

    class BoomProvider(ModelProvider):
        provider = "boom"

        async def complete(self, messages, tools=None, **cfg):
            raise CoreError("model exploded")

    if "boom" not in app_registries.models:
        app_registries.models.register("boom", BoomProvider())

    resp = client.post(
        "/api/runs",
        json={
            "manifest": {
                "id": "runner",
                "model": {"provider": "boom", "name": "x"},
                "prompt_ref": "prompts/echo_agent.md",
                "tools": [],
            },
            "input": "go",
        },
    )
    assert resp.status_code == 200
    assert '"type": "error"' in resp.text
    assert "model exploded" in resp.text


def test_memory_api_add_list_delete():
    add = client.post("/api/memory", json={"text": "loves orchids", "namespace": "apitest"})
    assert add.status_code == 200 and add.json()["ok"] is True

    listed = client.get("/api/memory", params={"namespace": "apitest"})
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any("orchids" in i["text"] for i in items)

    mid = next(i["id"] for i in items if "orchids" in i["text"])
    deleted = client.delete("/api/memory", params={"id": mid, "namespace": "apitest"})
    assert deleted.status_code == 200

    remaining = client.get("/api/memory", params={"namespace": "apitest"}).json()["items"]
    assert all(i["id"] != mid for i in remaining)


def test_memory_api_unknown_provider_is_400():
    resp = client.get("/api/memory", params={"provider": "does_not_exist"})
    assert resp.status_code == 400


def test_memory_api_bad_scope_is_400():
    resp = client.get("/api/memory", params={"scope": "bogus"})
    assert resp.status_code == 400


def test_run_persists_and_is_retrievable():
    import re

    resp = client.post(
        "/api/runs",
        json={
            "manifest": {
                "id": "runner",
                "model": {"provider": "echo", "name": "test-model"},
                "prompt_ref": "prompts/echo_agent.md",
                "tools": [],
            },
            "input": "remember me",
        },
    )
    assert resp.status_code == 200
    assert "run_started" in resp.text
    run_id = re.search(r'"run_id": "([0-9a-f]+)"', resp.text).group(1)

    listed = client.get("/api/runs").json()["runs"]
    assert any(r["id"] == run_id and r["status"] == "completed" for r in listed)

    record = client.get(f"/api/runs/{run_id}").json()
    assert record["answer"] == "remember me"
    assert "trace" in record and record["cost_usd"] == 0.0  # echo model is free

    exported = client.get(f"/api/runs/{run_id}/export").json()
    assert exported["id"] == run_id


def test_run_get_unknown_is_404():
    assert client.get("/api/runs/deadbeef00").status_code == 404
