"""PgVectorStore — durable, pgvector-backed ``VectorStore`` (Phase 3b, opt-in).

Same ``add``/``search`` contract as ``InMemoryVectorStore``, but rows persist
across process restarts and are shared across workers/processes (and, per the
PRD, with FloraLens). Selected opt-in via ``select_vector_store``: unset env
means the default (``InMemoryVectorStore``) stays byte-for-byte unchanged.
Mirrors the ``PostgresRunStore``/``select_run_store`` pattern in
``observability.py`` — lazy pool, schema created on first use, reachability
probed before opting in.

The ``pgvector`` Python package (the asyncpg codec) is imported lazily, only
inside the pool's connection-init hook — never at module import time — so
``import agent_core.vectorstore.pgvector`` (and thus ``import agent_core``)
works even when the optional ``pgvector`` package isn't installed. It is only
required when the pgvector backend is actually selected and used.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any

import asyncpg

from ..interfaces import VectorHit, VectorStore
from ..observability import ENV_DATABASE_URL, postgres_reachable
from .in_memory import InMemoryVectorStore

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Env-driven selection (mirrors ENV_DATABASE_URL / ENV_RUN_STORE style).
# --------------------------------------------------------------------------- #
ENV_VECTOR_STORE = "AGENTFORGE_VECTOR_STORE"
ENV_VECTOR_DIM = "AGENTFORGE_VECTOR_DIM"
DEFAULT_VECTOR_DIM = 1536  # openai text-embedding-3-small
DEFAULT_TABLE = "agent_vectors"

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PgVectorStore(VectorStore):
    """Vector index backed by Postgres + the ``pgvector`` extension."""

    def __init__(
        self,
        dsn: str,
        *,
        dim: int,
        table: str = DEFAULT_TABLE,
        pool: asyncpg.Pool | None = None,
    ) -> None:
        # Table is interpolated into DDL/DML below (asyncpg has no identifier
        # placeholder), so it's validated at the boundary rather than trusted.
        # fullmatch (not match): match's `$` also accepts a trailing newline.
        if not _TABLE_NAME_RE.fullmatch(table):
            raise ValueError(f"invalid table name: {table!r}")
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}")
        self._dsn = dsn
        self._dim = dim
        self._table = table
        self._pool = pool
        self._owns_pool = pool is None
        self._pool_lock = asyncio.Lock()

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        # Lazy import: only needed once the pgvector backend is actually used,
        # so the module (and `agent_core`) imports fine without the package.
        from pgvector.asyncpg import register_vector

        await register_vector(conn)

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is None:  # re-check: another task may have won the race
                pool = await asyncpg.create_pool(
                    self._dsn, min_size=1, max_size=5, init=self._init_connection
                )
                try:
                    async with pool.acquire() as conn:
                        await self._ensure_schema(conn)
                except BaseException:
                    # Never leak the freshly created pool (and its open
                    # connections) if schema setup fails — close it before
                    # propagating so a retry starts from a clean slate.
                    await pool.close()
                    raise
                self._pool = pool
        return self._pool

    async def _ensure_schema(self, conn: asyncpg.Connection) -> None:
        # CREATE EXTENSION / TABLE IF NOT EXISTS are not concurrency-safe in
        # Postgres: two processes racing on first use can still raise a
        # duplicate-object error. Treat that as success — another worker won.
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                "id text PRIMARY KEY, "
                f"embedding vector({self._dim}) NOT NULL, "
                "text text NOT NULL DEFAULT '', "
                "meta jsonb NOT NULL DEFAULT '{}'::jsonb)"
            )
        except (
            asyncpg.exceptions.DuplicateObjectError,
            asyncpg.exceptions.DuplicateTableError,
            asyncpg.exceptions.UniqueViolationError,
        ):
            pass
        # A pre-existing table with a different vector dimension is silently
        # kept by CREATE TABLE IF NOT EXISTS, so add()/search() would then fail
        # deep in Postgres on a size mismatch. Detect it and fail loudly with
        # actionable config guidance instead. (pgvector's atttypmod == the
        # declared dimension; -1 for an unbounded `vector`.)
        actual_dim = await conn.fetchval(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = $1::regclass AND attname = 'embedding' AND NOT attisdropped",
            self._table,
        )
        if actual_dim is not None and actual_dim > 0 and actual_dim != self._dim:
            raise ValueError(
                f"table {self._table!r} already exists with embedding dim {actual_dim}, "
                f"but this store is configured for dim {self._dim}; set "
                f"{ENV_VECTOR_DIM}={actual_dim} or use a different table"
            )

    async def add(
        self, id: str, vector: list[float], text: str = "", meta: dict[str, Any] | None = None
    ) -> None:
        if len(vector) != self._dim:
            raise ValueError(
                f"vector has {len(vector)} dims, expected {self._dim} for table {self._table!r}"
            )
        pool = await self._ensure_pool()
        meta_json = json.dumps(meta or {})
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self._table} (id, embedding, text, meta)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    text = EXCLUDED.text,
                    meta = EXCLUDED.meta
                """,
                id,
                vector,
                text,
                meta_json,
            )

    async def search(self, vector: list[float], k: int = 5) -> list[VectorHit]:
        if len(vector) != self._dim:
            raise ValueError(f"query vector has {len(vector)} dims, expected {self._dim}")
        if k <= 0:
            # Match InMemoryVectorStore: a non-positive k yields no hits (a raw
            # negative LIMIT would otherwise error in Postgres).
            return []
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, text, meta, 1 - (embedding <=> $1) AS score
                FROM {self._table}
                ORDER BY embedding <=> $1, id
                LIMIT $2
                """,
                vector,
                k,
            )
        hits = []
        for row in rows:
            meta = row["meta"]
            if isinstance(meta, str):  # jsonb comes back as str without a codec
                meta = json.loads(meta)
            hits.append(VectorHit(id=row["id"], score=row["score"], text=row["text"], meta=meta))
        return hits

    async def aclose(self) -> None:
        """Close the pool, if this instance owns it (i.e. wasn't injected)."""
        if self._pool is not None and self._owns_pool:
            await self._pool.close()
            self._pool = None


def select_vector_store() -> VectorStore:
    """Choose the vector store backend from env (mirrors ``select_run_store``).

    Default (``AGENTFORGE_VECTOR_STORE`` unset) is unchanged: an
    ``InMemoryVectorStore``. Setting ``AGENTFORGE_VECTOR_STORE=pgvector``
    (case-insensitive) plus a reachable ``DATABASE_URL`` opts into
    ``PgVectorStore`` — but only when Postgres actually answers at startup; a
    misconfigured or unreachable DB logs and falls back to in-memory rather
    than breaking startup. Embedding dimension comes from
    ``AGENTFORGE_VECTOR_DIM`` (default 1536, openai text-embedding-3-small).
    """
    backend = os.environ.get(ENV_VECTOR_STORE, "").strip().lower()
    if backend != "pgvector":
        logger.info(
            "%s not set to 'pgvector'; using in-memory vector store", ENV_VECTOR_STORE
        )
        return InMemoryVectorStore()

    # The reachability probe below only opens a TCP/auth connection; it can't
    # see whether the optional `pgvector` Python package (the asyncpg codec) is
    # installed. Without it, the FIRST add/search would raise ModuleNotFoundError
    # from the pool init hook — well past startup, with no fallback. Verify it
    # here so a missing extra degrades to in-memory instead.
    try:
        import pgvector.asyncpg  # noqa: F401
    except ImportError:
        logger.warning(
            "%s=pgvector but the 'pgvector' package is not installed "
            "(pip install 'agent-core[postgres]'); falling back to in-memory vector store",
            ENV_VECTOR_STORE,
        )
        return InMemoryVectorStore()

    dsn = os.environ.get(ENV_DATABASE_URL, "").strip()
    if not dsn:
        logger.warning(
            "%s=pgvector set but %s is empty; falling back to in-memory vector store",
            ENV_VECTOR_STORE,
            ENV_DATABASE_URL,
        )
        return InMemoryVectorStore()

    dim_raw = os.environ.get(ENV_VECTOR_DIM, "").strip()
    try:
        dim = int(dim_raw) if dim_raw else DEFAULT_VECTOR_DIM
        if dim <= 0:
            raise ValueError("dim must be positive")
    except ValueError:
        logger.warning(
            "%s=%r is not a valid positive integer; falling back to in-memory vector store",
            ENV_VECTOR_DIM,
            dim_raw,
        )
        return InMemoryVectorStore()

    try:
        reachable = asyncio.run(postgres_reachable(dsn))
    except RuntimeError:
        # Already inside a running event loop — can't run a nested asyncio.run();
        # fail safe rather than crash startup.
        logger.warning(
            "cannot probe Postgres from a running event loop; using in-memory vector store"
        )
        return InMemoryVectorStore()
    if not reachable:
        logger.warning(
            "%s set but Postgres is unreachable at startup; falling back to in-memory vector store",
            ENV_DATABASE_URL,
        )
        return InMemoryVectorStore()
    return PgVectorStore(dsn, dim=dim)
