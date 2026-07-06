"""InMemoryMemoryProvider — process-local long-term memory.

Default backend: no external deps, fully testable. Relevance is a simple
word-overlap score (good enough for demos/tests). mem0 is the semantic backend.
Memories persist for the process lifetime, bucketed by (scope, namespace).
"""

import uuid

from ..interfaces import MemoryItem, MemoryProvider, Scope


class InMemoryMemoryProvider(MemoryProvider):
    provider = "in_memory"

    def __init__(self, max_per_bucket: int = 1000) -> None:
        self._store: dict[tuple[str, str], list[MemoryItem]] = {}
        self._max_per_bucket = max_per_bucket

    @staticmethod
    def _key(scope: Scope, namespace: str) -> tuple[str, str]:
        return (str(scope), namespace)

    async def add(self, scope: Scope, namespace: str, items: list[MemoryItem]) -> None:
        bucket = self._store.setdefault(self._key(scope, namespace), [])
        for item in items:
            stored = item.model_copy()  # don't mutate the caller's object
            if stored.id is None:
                stored.id = uuid.uuid4().hex
            bucket.append(stored)
        # Bound growth (oldest evicted first) so a long-lived process is safe.
        if len(bucket) > self._max_per_bucket:
            del bucket[: len(bucket) - self._max_per_bucket]

    async def search(
        self, scope: Scope, namespace: str, query: str, k: int = 5
    ) -> list[MemoryItem]:
        bucket = self._store.get(self._key(scope, namespace), [])
        terms = set(query.lower().split())
        scored = sorted(
            bucket,
            key=lambda it: len(terms & set(it.text.lower().split())),
            reverse=True,
        )
        # Only return items with at least one overlapping term.
        return [it for it in scored if terms & set(it.text.lower().split())][:k]

    async def delete(self, scope: Scope, namespace: str, ids: list[str]) -> None:
        key = self._key(scope, namespace)
        self._store[key] = [
            it for it in self._store.get(key, []) if it.id not in ids
        ]

    async def all(self, scope: Scope, namespace: str) -> list[MemoryItem]:
        return list(self._store.get(self._key(scope, namespace), []))
