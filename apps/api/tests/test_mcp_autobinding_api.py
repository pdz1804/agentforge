"""MCP auto-binding through the live `/api/runs` SSE endpoint.

`compile_agent` is called from inside the endpoint's already-running event
loop (see `app.main.run_agent`'s `event_stream` async generator), which is
exactly the case `agent_core.runtime._run_sync` exists for: MCP discovery is
async, but `asyncio.run` cannot nest inside a loop that is already running.
This proves that thread-fallback path for real, end to end, via a stub MCP
connector (no real server, fully offline).
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from agent_core import MCPConnector, MCPServerBinding, ModelProvider, ModelResponse, ToolCall, build_mcp_tools

from app.main import app
from app.main import registries as app_registries

client = TestClient(app)


class _StubWeatherMCPConnector(MCPConnector):
    async def discover(self, server_cfg: dict[str, Any]):
        async def call_fn(name: str, args: dict[str, Any]) -> str:
            return f"sunny in {args.get('city', 'nowhere')}"

        return build_mcp_tools(
            [
                {
                    "name": "get_weather_api_test",
                    "description": "look up the weather",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                }
            ],
            call_fn,
        )


class _ScriptedModelProvider(ModelProvider):
    """Calls the auto-bound MCP tool once, then answers with its result."""

    provider = "mcp_api_test_scripted"

    async def complete(self, messages, tools=None, **cfg) -> ModelResponse:
        last_tool = next((m.content for m in reversed(messages) if m.role == "tool"), None)
        if last_tool is not None:
            return ModelResponse(text=last_tool)
        return ModelResponse(
            tool_calls=[ToolCall(name="get_weather_api_test", args={"city": "Hanoi"})]
        )


app_registries.mcp.register("stub_weather_mcp", MCPServerBinding(_StubWeatherMCPConnector(), {}))
app_registries.models.register("mcp_api_test_scripted", _ScriptedModelProvider())


def test_run_endpoint_auto_binds_and_calls_mcp_tool():
    resp = client.post(
        "/api/runs",
        json={
            "manifest": {
                "id": "mcp_api_runner",
                "model": {"provider": "mcp_api_test_scripted", "name": "test-model"},
                "prompt_ref": "prompts/echo_agent.md",
                "tools": [],
                "mcp_servers": ["stub_weather_mcp"],
            },
            "input": "what's the weather",
        },
    )
    assert resp.status_code == 200
    # A successful stream ending in the auto-bound tool's actual output proves
    # compile_agent's MCP discovery -> adaptation -> invocation ran to
    # completion inside the endpoint's already-running event loop.
    assert '"type": "error"' not in resp.text
    assert '"type": "done"' in resp.text
    assert "sunny in Hanoi" in resp.text
