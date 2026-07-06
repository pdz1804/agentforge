"""InMemoryVectorStore — process-local cosine-similarity index.

Default backend: no external deps, fully testable. Process-local and unbounded
(single-worker, demo/dev scale). A durable, multi-worker pgvector store (shared
with FloraLens) implements the same ``VectorStore`` interface later.
"""

import math
from typing import Any

from ..interfaces import VectorHit, VectorStore


def cosine(a: list[float], b: list[float]) -> float:
    # strict=True: a dimension mismatch (e.g. vectors from different embedding
    # models) raises rather than silently scoring on the truncated overlap.
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._items: list[tuple[str, list[float], str, dict[str, Any]]] = []

    async def add(
        self, id: str, vector: list[float], text: str = "", meta: dict[str, Any] | None = None
    ) -> None:
        self._items = [it for it in self._items if it[0] != id]  # upsert by id
        self._items.append((id, vector, text, meta or {}))

    async def search(self, vector: list[float], k: int = 5) -> list[VectorHit]:
        scored = [
            VectorHit(id=i, score=cosine(vector, v), text=t, meta=m)
            for (i, v, t, m) in self._items
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]
