"""Vector store + EmbeddingSearchTool + MCP adapter — all offline with fakes."""

import asyncio

from agent_core import (
    EmbeddingSearchTool,
    InMemoryVectorStore,
    ToolResult,
    build_mcp_tools,
)
from agent_core.vectorstore.in_memory import cosine


# --- vector store --------------------------------------------------------- #
def test_cosine_ranks_nearest_first():
    async def scenario():
        store = InMemoryVectorStore()
        await store.add("a", [1.0, 0.0], "east")
        await store.add("b", [0.0, 1.0], "north")
        await store.add("c", [0.9, 0.1], "east-ish")
        hits = await store.search([1.0, 0.0], k=2)
        assert [h.id for h in hits] == ["a", "c"]  # nearest by cosine
        assert hits[0].score > hits[1].score

    asyncio.run(scenario())


def test_upsert_replaces_by_id():
    async def scenario():
        store = InMemoryVectorStore()
        await store.add("x", [1.0, 0.0], "v1")
        await store.add("x", [0.0, 1.0], "v2")
        hits = await store.search([0.0, 1.0], k=5)
        assert len(hits) == 1 and hits[0].text == "v2"

    asyncio.run(scenario())


def test_cosine_zero_vector_is_safe():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# --- embedding search tool (fake deterministic embed) --------------------- #
async def _fake_embed(text: str) -> list[float]:
    # 3-dim bag over keywords -> deterministic, offline.
    return [
        float(text.lower().count("rose")),
        float(text.lower().count("tulip")),
        float(text.lower().count("care")),
    ]


def test_embedding_search_returns_scored_matches():
    async def scenario():
        tool = EmbeddingSearchTool(InMemoryVectorStore(), _fake_embed)
        await tool.index("d1", "the rose is a classic flower")
        await tool.index("d2", "tulip care and watering")
        result = await tool.run(query="rose")
        assert isinstance(result, ToolResult)
        assert result.ok is True
        assert "rose" in result.output
        assert result.meta["count"] >= 1

    asyncio.run(scenario())


def test_embedding_search_reports_embed_failure_gracefully():
    async def boom_embed(text: str) -> list[float]:
        raise RuntimeError("embed down")

    tool = EmbeddingSearchTool(InMemoryVectorStore(), boom_embed)
    result = asyncio.run(tool.run(query="x"))
    assert result.ok is False
    assert "embed down" in result.error


# --- MCP adapter (fake descriptors + call fn) ----------------------------- #
def test_build_mcp_tools_adapts_schema_and_calls():
    calls = []

    async def fake_call(name, args):
        calls.append((name, args))
        return f"ran {name}"

    tool_defs = [
        {
            "name": "get_weather",
            "description": "look up weather",
            "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}},
        }
    ]
    tools = build_mcp_tools(tool_defs, fake_call)
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "get_weather"
    # MCP inputSchema is surfaced verbatim as the LLM-facing schema.
    assert tool.json_schema()["properties"]["city"]["type"] == "string"

    result = asyncio.run(tool.run(city="Hanoi"))
    assert result.ok is True
    assert result.output == "ran get_weather"
    assert calls == [("get_weather", {"city": "Hanoi"})]


def test_build_mcp_tools_object_descriptors_and_call_errors():
    class Def:
        name = "boom"
        description = "d"
        inputSchema = {"type": "object"}

    async def failing_call(name, args):
        raise RuntimeError("mcp offline")

    tool = build_mcp_tools([Def()], failing_call)[0]
    result = asyncio.run(tool.run())
    assert result.ok is False
    assert "mcp offline" in result.error
