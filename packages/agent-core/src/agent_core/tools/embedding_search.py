"""EmbeddingSearchTool — semantic search over an indexed corpus.

Owns a ``VectorStore`` + an embed fn. ``index`` embeds and stores a document;
``run`` embeds the query and returns top matches with similarity scores. Both
the store and embed fn are injected, so it is fully testable offline.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from ..errors import AgentCoreError
from ..interfaces import BaseTool, ToolResult, VectorStore

EmbedFn = Callable[[str], Awaitable[list[float]]]


class EmbeddingSearchArgs(BaseModel):
    query: str
    k: int = Field(default=5, ge=1, le=20)


class EmbeddingSearchTool(BaseTool):
    name = "embedding_search"
    description = (
        "Semantic search over the indexed corpus; returns the top matching "
        "passages with similarity scores."
    )
    args_schema = EmbeddingSearchArgs

    def __init__(self, store: VectorStore, embed_fn: EmbedFn) -> None:
        self._store = store
        self._embed = embed_fn

    async def index(self, doc_id: str, text: str, meta: dict[str, Any] | None = None) -> None:
        vector = await self._embed(text)
        await self._store.add(doc_id, vector, text, meta)

    async def run(self, **kwargs: Any) -> ToolResult:
        args = self.validate_args(**kwargs)
        try:
            vector = await self._embed(args.query)
            hits = await self._store.search(vector, args.k)
        except AgentCoreError as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:
            return ToolResult(ok=False, error=f"embedding search failed: {exc}")

        lines = [f"- [{h.score:.3f}] {h.text[:200]}" for h in hits]
        return ToolResult(
            ok=True, output="\n".join(lines) or "no results", meta={"count": len(hits)}
        )
