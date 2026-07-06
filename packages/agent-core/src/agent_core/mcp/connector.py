"""Adapt MCP-server tools into the harness's BaseTool.

``build_mcp_tools`` is the pure, testable core: given MCP tool descriptors and an
async ``call_fn(name, args)``, it produces BaseTools whose JSON schema is the
MCP ``inputSchema`` (surfaced to the LLM verbatim). ``StdioMCPConnector`` is the
live transport (lazy ``mcp`` package + a running server; not unit-tested).
"""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..errors import AgentCoreError
from ..interfaces import BaseTool, MCPConnector, ToolResult

CallFn = Callable[[str, dict[str, Any]], Awaitable[Any]]


class _PassthroughArgs(BaseModel):
    model_config = ConfigDict(extra="allow")


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


class MCPTool(BaseTool):
    """A single MCP tool exposed through the BaseTool contract."""

    args_schema = _PassthroughArgs

    def __init__(
        self, name: str, description: str, input_schema: dict[str, Any] | None, call_fn: CallFn
    ) -> None:
        self.name = name
        self.description = description or ""
        self._input_schema = input_schema or {"type": "object", "properties": {}}
        self._call_fn = call_fn

    def json_schema(self) -> dict[str, Any]:
        return self._input_schema

    async def run(self, **kwargs: Any) -> ToolResult:
        try:
            output = await self._call_fn(self.name, kwargs)
        except Exception as exc:
            return ToolResult(ok=False, error=f"mcp tool '{self.name}' failed: {exc}")
        return ToolResult(ok=True, output=output)


def build_mcp_tools(tool_defs: list[Any], call_fn: CallFn) -> list[MCPTool]:
    """Adapt MCP tool descriptors (dicts or objects) into BaseTools."""
    tools: list[MCPTool] = []
    for td in tool_defs:
        name = _get(td, "name")
        if not name:
            continue
        schema = _get(td, "inputSchema") or _get(td, "input_schema")
        tools.append(MCPTool(name, _get(td, "description"), schema, call_fn))
    return tools


def _result_text(result: Any) -> str:
    """Best-effort extraction of text from an MCP CallToolResult."""
    content = _get(result, "content")
    if content is None:
        return str(result)
    parts = [str(_get(block, "text") or "") for block in content]
    return "\n".join(p for p in parts if p) or str(result)


class StdioMCPConnector(MCPConnector):
    """Connect to an MCP server over stdio, list its tools, and adapt them.

    Requires the ``mcp`` package and a running server. For simplicity each
    adapted tool opens a fresh session per call (stateless, robust). LIMITATION:
    servers that accumulate state across calls (sessions, caches) are reset each
    call and are not supported by this connector; reuse one session for those.
    """

    async def discover(self, server_cfg: dict[str, Any]) -> list[BaseTool]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover - optional extra
            raise AgentCoreError(
                "the 'mcp' package is not installed; install with: pip install 'agent-core[mcp]'"
            ) from exc

        params = StdioServerParameters(
            command=server_cfg["command"],
            args=server_cfg.get("args", []),
            env=server_cfg.get("env"),
        )

        async def call_fn(name: str, args: dict[str, Any]) -> str:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return _result_text(await session.call_tool(name, args))

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()

        return build_mcp_tools(listed.tools, call_fn)
