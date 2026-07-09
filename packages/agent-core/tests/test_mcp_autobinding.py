"""MCP `mcp_servers` auto-binding — offline smoke (PRD Section 8.3 MCPConnector /
Section 5 "connect an MCP server & call its tool ≤ 20 min via config").

A manifest that declares `mcp_servers` gets those servers' tools discovered and
adapted into its toolset automatically by `compile_agent` — no per-tool entry
in `tools:` needed. No real MCP server is involved: a stub `MCPConnector`
proves discover -> adapt -> the tool is callable in a run, entirely offline.
Manifests that omit `mcp_servers` (every pre-existing manifest) are unaffected
— the auto-binding loop never runs for them.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_core import (
    MCPConnector,
    MCPServerBinding,
    ModelProvider,
    ModelResponse,
    ToolCall,
    build_default_registries,
    build_mcp_tools,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
)
from agent_core.errors import AgentCoreError, UnknownReferenceError


class StubMCPConnector(MCPConnector):
    """A fake MCP connector: no subprocess, no server — canned tool defs and
    an in-process call_fn that records every invocation."""

    def __init__(self, tool_defs: list[dict], calls: list[tuple[str, dict]]) -> None:
        self._tool_defs = tool_defs
        self._calls = calls

    async def discover(self, server_cfg: dict[str, Any]):
        async def call_fn(name: str, args: dict[str, Any]) -> str:
            self._calls.append((name, args))
            return f"stub result for {name}({args})"

        return build_mcp_tools(self._tool_defs, call_fn)


class ScriptedModelProvider(ModelProvider):
    provider = "scripted"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses
        self._i = 0

    async def complete(self, messages, tools=None, **cfg) -> ModelResponse:
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp


def _manifest(mcp_servers: list[str], tools: list[str] | None = None) -> dict:
    return {
        "id": "mcp_user",
        "model": {"provider": "scripted", "name": "x"},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": tools or [],
        "mcp_servers": mcp_servers,
    }


def test_no_mcp_servers_declared_is_a_pure_no_op():
    # Default (empty mcp_servers, every pre-existing manifest): compile_agent
    # never touches registries.mcp at all.
    registries = build_default_registries()
    registries.models.register("scripted", ScriptedModelProvider([ModelResponse(text="hi")]))
    manifest = load_manifest_dict(_manifest([]))
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    result = asyncio.run(agent.arun("go"))

    assert result.answer == "hi"


def test_mcp_server_tools_are_discovered_adapted_and_callable():
    calls: list[tuple[str, dict]] = []
    tool_defs = [
        {
            "name": "get_weather",
            "description": "look up the weather for a city",
            "inputSchema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]
    registries = build_default_registries()
    registries.models.register(
        "scripted",
        ScriptedModelProvider(
            [
                ModelResponse(tool_calls=[ToolCall(name="get_weather", args={"city": "Hanoi"})]),
                ModelResponse(text="done"),
            ]
        ),
    )
    registries.mcp.register(
        "weather_mcp",
        MCPServerBinding(StubMCPConnector(tool_defs, calls), {"command": "stub"}),
    )
    manifest = load_manifest_dict(_manifest(["weather_mcp"]))
    resolve_manifest(manifest, registries)  # 'weather_mcp' resolves via registries.mcp

    agent = compile_agent(manifest, registries)  # discover -> adapt happens here
    result = asyncio.run(agent.arun("what's the weather in Hanoi"))  # the tool is callable in a run

    assert result.answer == "done"
    assert calls == [("get_weather", {"city": "Hanoi"})]  # the MCP tool actually ran
    tool_events = [e for e in result.trace if e.type == "tool"]
    assert tool_events[0].node == "get_weather"
    assert "stub result" in tool_events[0].detail


def test_mcp_tool_name_collision_with_existing_tool_is_rejected():
    tool_defs = [{"name": "echo", "description": "collides", "inputSchema": {"type": "object"}}]
    registries = build_default_registries()  # already has a built-in tool named "echo"
    registries.models.register("scripted", ScriptedModelProvider([ModelResponse(text="x")]))
    registries.mcp.register("dup_mcp", MCPServerBinding(StubMCPConnector(tool_defs, []), {}))
    manifest = load_manifest_dict(_manifest(["dup_mcp"], tools=["echo"]))
    resolve_manifest(manifest, registries)

    with pytest.raises(AgentCoreError, match="collides"):
        compile_agent(manifest, registries)


def test_unregistered_mcp_server_fails_resolution_clearly():
    registries = build_default_registries()
    registries.models.register("scripted", ScriptedModelProvider([ModelResponse(text="x")]))
    manifest = load_manifest_dict(_manifest(["ghost_mcp"]))

    with pytest.raises(UnknownReferenceError, match="ghost_mcp"):
        resolve_manifest(manifest, registries)
