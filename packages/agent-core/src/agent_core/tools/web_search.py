"""WebSearchTool — web search via Tavily.

The HTTP call is behind an injectable ``search_fn`` so tests run offline with a
fake backend; production resolves ``TAVILY_API_KEY`` lazily and calls Tavily.
"""

import os
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from ..errors import AgentCoreError
from ..interfaces import BaseTool, ToolResult

# An async backend: (query, max_results) -> list of {title, url, content} dicts.
SearchFn = Callable[[str, int], Awaitable[list[dict[str, Any]]]]


class WebSearchArgs(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=20)


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web (via Tavily) and return top results as title, url, and snippet."
    args_schema = WebSearchArgs

    def __init__(self, search_fn: SearchFn | None = None, api_key: str | None = None) -> None:
        self._search_fn = search_fn
        self._api_key = api_key

    async def run(self, **kwargs: Any) -> ToolResult:
        args = self.validate_args(**kwargs)
        try:
            results = await (self._search_fn or self._tavily_search)(
                args.query, args.max_results
            )
        except AgentCoreError as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # network/HTTP errors -> tool failure, not a crash
            return ToolResult(ok=False, error=f"web search failed: {exc}")

        lines = [
            f"- {r.get('title', 'untitled')} ({r.get('url', '')}): "
            f"{(r.get('content') or '')[:200]}"
            for r in results
        ]
        return ToolResult(
            ok=True, output="\n".join(lines) or "no results", meta={"count": len(results)}
        )

    async def _tavily_search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        api_key = self._api_key or os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise AgentCoreError("TAVILY_API_KEY is not set; cannot run web search")
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
