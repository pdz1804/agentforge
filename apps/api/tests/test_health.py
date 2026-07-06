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
    assert "echo" in resp.json()["tools"]


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
