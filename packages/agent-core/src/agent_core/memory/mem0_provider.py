"""Mem0MemoryProvider — semantic long-term memory via mem0 (optional backend).

mem0 is imported lazily (optional extra) and uses OPENAI_API_KEY for its
embedder/LLM by default. It is synchronous; calls run inline. Same
``MemoryProvider`` interface as InMemory, so it is a drop-in swap.
"""

import asyncio
from typing import Any

from ..errors import AgentCoreError
from ..interfaces import MemoryItem, MemoryProvider, Scope


class Mem0MemoryProvider(MemoryProvider):
    provider = "mem0"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config
        self._client: Any = None

    def _memory(self) -> Any:
        if self._client is None:
            try:
                from mem0 import Memory
            except ImportError as exc:  # pragma: no cover - optional extra
                raise AgentCoreError(
                    "the 'mem0ai' package is not installed; "
                    "install with: pip install 'agent-core[mem0]'"
                ) from exc
            self._client = (
                Memory.from_config(self._config) if self._config else Memory()
            )
        return self._client

    @staticmethod
    def _uid(scope: Scope, namespace: str) -> str:
        return f"{namespace}:{scope}"

    async def add(self, scope: Scope, namespace: str, items: list[MemoryItem]) -> None:
        mem = self._memory()
        uid = self._uid(scope, namespace)
        for item in items:
            # mem0 is synchronous + does network I/O — offload so the event loop
            # is never blocked.
            await asyncio.to_thread(mem.add, item.text, user_id=uid, metadata=item.meta or None)

    async def search(
        self, scope: Scope, namespace: str, query: str, k: int = 5
    ) -> list[MemoryItem]:
        mem = self._memory()
        res = await asyncio.to_thread(
            mem.search, query, user_id=self._uid(scope, namespace), limit=k
        )
        return _to_items(res)

    async def delete(self, scope: Scope, namespace: str, ids: list[str]) -> None:
        mem = self._memory()
        for memory_id in ids:
            await asyncio.to_thread(mem.delete, memory_id=memory_id)

    async def all(self, scope: Scope, namespace: str) -> list[MemoryItem]:
        mem = self._memory()
        res = await asyncio.to_thread(mem.get_all, user_id=self._uid(scope, namespace))
        return _to_items(res)


def _to_items(res: Any) -> list[MemoryItem]:
    rows = res.get("results", res) if isinstance(res, dict) else res
    return [
        MemoryItem(id=r.get("id"), text=r.get("memory", ""), meta=r.get("metadata") or {})
        for r in rows
    ]
