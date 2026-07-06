"""WebSearchTool — offline via an injected fake backend."""

import asyncio

from agent_core import WebSearchTool
from agent_core.interfaces import ToolResult


def test_web_search_formats_results_from_backend():
    async def fake_search(query, max_results):
        assert query == "flowers"
        return [
            {"title": "Roses", "url": "http://x/roses", "content": "red flowers"},
            {"title": "Tulips", "url": "http://x/tulips", "content": "spring flowers"},
        ]

    tool = WebSearchTool(search_fn=fake_search)
    result = asyncio.run(tool.run(query="flowers"))
    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert "Roses" in result.output and "http://x/tulips" in result.output
    assert result.meta["count"] == 2


def test_web_search_missing_key_returns_error_result():
    # No search_fn and no TAVILY_API_KEY -> graceful tool error, not a crash.
    tool = WebSearchTool()
    result = asyncio.run(tool.run(query="anything"))
    assert result.ok is False
    assert "TAVILY_API_KEY" in result.error


def test_web_search_validates_max_results():
    import pytest
    from pydantic import ValidationError

    tool = WebSearchTool(search_fn=lambda q, n: None)
    with pytest.raises(ValidationError):
        asyncio.run(tool.run(query="x", max_results=999))
