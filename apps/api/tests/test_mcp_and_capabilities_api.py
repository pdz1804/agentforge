"""GET /api/mcp (PRD Section 11) + http_fetch showing up in capability discovery.

No real MCP server/subprocess is ever spawned here: `build_default_registries`
only registers the `everything` server's connector + static config, it never
calls `.discover()` (that only happens inside `compile_agent` when a manifest
actually lists `mcp_servers`, covered by `test_mcp_autobinding_api.py`).
"""

import json
import os

from fastapi.testclient import TestClient

from agent_core.defaults import ENV_MCP_SERVERS, build_default_registries

from app.main import app

client = TestClient(app)


def test_tools_list_includes_http_fetch():
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    assert "http_fetch" in resp.json()["tools"]


def test_health_tools_include_http_fetch():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "http_fetch" in resp.json()["tools"]


def test_list_mcp_servers_returns_everything_server():
    resp = client.get("/api/mcp")
    assert resp.status_code == 200
    servers = resp.json()["servers"]
    names = [s["name"] for s in servers]
    assert "everything" in names

    everything = next(s for s in servers if s["name"] == "everything")
    assert everything["command"] == "npx"
    assert everything["configured_env"] == []  # no auth needed for the public server


def test_list_mcp_servers_never_leaks_env_values():
    # Register a server with a fake secret directly on the app's live registries
    # (mirrors how AGENTFORGE_MCP_SERVERS/env would supply one) and confirm the
    # value never appears in the response, only the key name.
    from agent_core import MCPServerBinding, StdioMCPConnector

    from app.main import registries as app_registries

    if "leak_test_mcp" not in app_registries.mcp:
        app_registries.mcp.register(
            "leak_test_mcp",
            MCPServerBinding(
                StdioMCPConnector(),
                {"command": "echo", "args": [], "env": {"API_TOKEN": "super-secret-value"}},
            ),
        )

    resp = client.get("/api/mcp")
    assert resp.status_code == 200
    assert "super-secret-value" not in resp.text

    entry = next(s for s in resp.json()["servers"] if s["name"] == "leak_test_mcp")
    assert entry["configured_env"] == ["API_TOKEN"]


def _with_env(key: str, value: str | None):
    """Context-manager-free env override helper: returns (previous_value)."""
    previous = os.environ.get(key)
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
    return previous


def _restore_env(key: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = previous


def test_extra_mcp_servers_env_registers_authenticated_server():
    extra = [
        {
            "name": "private_test_mcp",
            "command": "node",
            "args": ["server.js"],
            "env": {"PRIVATE_TOKEN": "sekret"},
        }
    ]
    previous = _with_env(ENV_MCP_SERVERS, json.dumps(extra))
    try:
        registries = build_default_registries()
    finally:
        _restore_env(ENV_MCP_SERVERS, previous)

    assert "private_test_mcp" in registries.mcp.list()
    binding = registries.mcp.get("private_test_mcp")
    assert binding.config["command"] == "node"
    assert binding.config["env"] == {"PRIVATE_TOKEN": "sekret"}
    # the default public server is still registered alongside the extra one
    assert "everything" in registries.mcp.list()


def test_malformed_extra_mcp_servers_env_does_not_break_registration():
    previous = _with_env(ENV_MCP_SERVERS, "not valid json")
    try:
        registries = build_default_registries()  # must not raise
    finally:
        _restore_env(ENV_MCP_SERVERS, previous)

    assert "everything" in registries.mcp.list()
