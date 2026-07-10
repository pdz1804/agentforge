"""PgVectorStore + select_vector_store (Phase 3b, opt-in).

The fallback-selection test (no env set -> InMemoryVectorStore) always runs,
no DB required. The real PgVectorStore tests need a reachable Postgres with
the pgvector extension available — set AGENTFORGE_TEST_PGVECTOR_DSN and they
run; otherwise they're skipped rather than failing a machine with no DB.
"""

import asyncio
import os
import uuid

import pytest

from agent_core.vectorstore import InMemoryVectorStore, PgVectorStore, select_vector_store

TEST_DSN = os.environ.get("AGENTFORGE_TEST_PGVECTOR_DSN", "")

requires_pgvector_db = pytest.mark.skipif(
    not TEST_DSN, reason="no pgvector DSN (set AGENTFORGE_TEST_PGVECTOR_DSN)"
)


# --------------------------------------------------------------------------- #
# Pure: env-based selection falls back safely (no DB required).
# --------------------------------------------------------------------------- #
def test_select_vector_store_defaults_to_in_memory_when_unset(monkeypatch):
    monkeypatch.delenv("AGENTFORGE_VECTOR_STORE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = select_vector_store()
    assert isinstance(store, InMemoryVectorStore)


def test_select_vector_store_falls_back_when_url_missing(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_VECTOR_STORE", "pgvector")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = select_vector_store()
    assert isinstance(store, InMemoryVectorStore)


def test_select_vector_store_falls_back_when_unreachable(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_VECTOR_STORE", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "postgresql://nope:nope@localhost:1/nope")
    store = select_vector_store()
    assert isinstance(store, InMemoryVectorStore)


def test_select_vector_store_falls_back_on_bad_dim(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_VECTOR_STORE", "PgVector")  # case-insensitive
    monkeypatch.setenv("DATABASE_URL", "postgresql://nope:nope@localhost:1/nope")
    monkeypatch.setenv("AGENTFORGE_VECTOR_DIM", "not-an-int")
    store = select_vector_store()
    assert isinstance(store, InMemoryVectorStore)


def test_select_vector_store_ignores_other_backend_values(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_VECTOR_STORE", "in_memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://irrelevant/because-not-pgvector")
    store = select_vector_store()
    assert isinstance(store, InMemoryVectorStore)


# --------------------------------------------------------------------------- #
# Pure: constructor validation (no DB required — __init__ never connects).
# --------------------------------------------------------------------------- #
def test_pgvector_store_rejects_invalid_table_name():
    with pytest.raises(ValueError, match="table name"):
        PgVectorStore("postgresql://x/y", dim=3, table="bad; drop table x")


def test_pgvector_store_rejects_nonpositive_dim():
    with pytest.raises(ValueError, match="dim"):
        PgVectorStore("postgresql://x/y", dim=0)


# --------------------------------------------------------------------------- #
# Requires a real reachable Postgres with the pgvector extension available.
# --------------------------------------------------------------------------- #
@requires_pgvector_db
def test_pgvector_store_add_search_ranks_by_cosine():
    table = f"agent_vectors_test_{uuid.uuid4().hex[:12]}"

    async def scenario():
        store = PgVectorStore(TEST_DSN, dim=3, table=table)
        try:
            await store.add("a", [1.0, 0.0, 0.0], "east", {"tag": "a"})
            await store.add("b", [0.0, 1.0, 0.0], "north", {"tag": "b"})
            await store.add("c", [0.9, 0.1, 0.0], "east-ish", {"tag": "c"})

            hits = await store.search([1.0, 0.0, 0.0], k=2)
            assert [h.id for h in hits] == ["a", "c"]  # nearest by cosine first
            assert hits[0].score > hits[1].score
            assert hits[0].score == pytest.approx(1.0, abs=1e-6)
            assert hits[0].text == "east"
            assert hits[0].meta == {"tag": "a"}
        finally:
            await _drop_table(store, table)
            await store.aclose()

    asyncio.run(scenario())


@requires_pgvector_db
def test_pgvector_store_add_rejects_dim_mismatch():
    table = f"agent_vectors_test_{uuid.uuid4().hex[:12]}"

    async def scenario():
        store = PgVectorStore(TEST_DSN, dim=3, table=table)
        try:
            with pytest.raises(ValueError, match="dims"):
                await store.add("a", [1.0, 0.0], "wrong dim")
        finally:
            await _drop_table(store, table)
            await store.aclose()

    asyncio.run(scenario())


@requires_pgvector_db
def test_pgvector_store_upsert_replaces_by_id():
    table = f"agent_vectors_test_{uuid.uuid4().hex[:12]}"

    async def scenario():
        store = PgVectorStore(TEST_DSN, dim=3, table=table)
        try:
            await store.add("x", [1.0, 0.0, 0.0], "v1")
            await store.add("x", [0.0, 1.0, 0.0], "v2")  # upsert: same id, new vector

            hits = await store.search([0.0, 1.0, 0.0], k=5)
            assert len(hits) == 1
            assert hits[0].id == "x"
            assert hits[0].text == "v2"
            assert hits[0].score == pytest.approx(1.0, abs=1e-6)
        finally:
            await _drop_table(store, table)
            await store.aclose()

    asyncio.run(scenario())


@requires_pgvector_db
def test_pgvector_store_survives_a_fresh_instance():
    """Simulates a process restart: a new store instance sees prior adds."""
    table = f"agent_vectors_test_{uuid.uuid4().hex[:12]}"

    async def scenario():
        store1 = PgVectorStore(TEST_DSN, dim=3, table=table)
        await store1.add("persist", [1.0, 0.0, 0.0], "still here")
        await store1.aclose()

        store2 = PgVectorStore(TEST_DSN, dim=3, table=table)
        try:
            hits = await store2.search([1.0, 0.0, 0.0], k=1)
            assert len(hits) == 1
            assert hits[0].id == "persist"
        finally:
            await _drop_table(store2, table)
            await store2.aclose()

    asyncio.run(scenario())


async def _drop_table(store: PgVectorStore, table: str) -> None:
    # Reaches into the private pool to drop the scratch table created for this
    # test run; not part of PgVectorStore's public contract.
    pool = await store._ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {table}")
