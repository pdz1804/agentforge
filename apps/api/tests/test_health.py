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
