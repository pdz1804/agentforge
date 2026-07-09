"""Postgres-backed run store + trace retention (Phase 8).

Pure tests (truncate_trace, select_run_store fallback) always run. The real
PostgresRunStore tests need a reachable database — set
AGENTFORGE_TEST_DATABASE_URL (falls back to DATABASE_URL, then the
docker-compose default) and they run; otherwise they're skipped rather than
failing a machine with no Postgres.
"""

import asyncio
import os
import uuid

import pytest

from agent_core.observability import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_RETENTION_ROWS,
    InMemoryRunStore,  # default store, for comparison
    PostgresRunStore,
    RunRecord,
    postgres_reachable,
    select_run_store,
    truncate_trace,
)
from agent_core.runtime import TraceEvent

TEST_DSN = (
    os.environ.get("AGENTFORGE_TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://agentforge:agentforge@localhost:5432/agentforge"
)


def _db_reachable() -> bool:
    try:
        return asyncio.run(postgres_reachable(TEST_DSN, timeout_s=1.5))
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_reachable(), reason=f"no Postgres reachable at {TEST_DSN!r}"
)


def _event(step: int, type_: str = "tool") -> TraceEvent:
    return TraceEvent(step=step, type=type_, node="n")


def _rec(rid: str, trace: list[TraceEvent] | None = None) -> RunRecord:
    return RunRecord(
        id=rid,
        manifest_id="m",
        model="x",
        input="in",
        status="completed",
        answer="ok",
        trace=trace or [],
        usage={"input_tokens": 1, "output_tokens": 2},
        cost_usd=0.001,
        created_at="2026-07-10T00:00:00+00:00",
    )


# --------------------------------------------------------------------------- #
# Pure: trace truncation (no DB)
# --------------------------------------------------------------------------- #
def test_truncate_trace_noop_when_under_cap():
    trace = [_event(i) for i in range(5)]
    out, sampled = truncate_trace(trace, max_events=10)
    assert out == trace
    assert sampled is False


def test_truncate_trace_drops_middle_keeps_head_marker_tail():
    trace = [_event(i) for i in range(20)]
    out, sampled = truncate_trace(trace, max_events=10)
    assert sampled is True
    assert len(out) == 10
    # head preserved in order
    assert [e.step for e in out[:8]] == list(range(8))
    # marker records the drop
    assert out[8].type == "sampled"
    assert "11 event(s) omitted" in out[8].detail
    # terminal event preserved (the outcome-defining one)
    assert out[-1] == trace[-1]


def test_truncate_trace_rejects_tiny_cap():
    with pytest.raises(ValueError):
        truncate_trace([_event(0)], max_events=2)


# --------------------------------------------------------------------------- #
# Pure: env-based selection falls back safely (no DB required to prove this —
# an unreachable DSN must not raise, and no env set must keep the default).
# --------------------------------------------------------------------------- #
def test_select_run_store_defaults_to_in_memory_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AGENTFORGE_RUN_STORE", raising=False)
    assert isinstance(select_run_store(), InMemoryRunStore)


def test_select_run_store_falls_back_when_unreachable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nope:nope@localhost:1/nope")
    store = select_run_store()
    assert isinstance(store, InMemoryRunStore)


def test_select_run_store_opts_in_via_flag_without_url_falls_back(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTFORGE_RUN_STORE", "postgres")
    assert isinstance(select_run_store(), InMemoryRunStore)


# --------------------------------------------------------------------------- #
# Requires a real Postgres.
# --------------------------------------------------------------------------- #
@requires_db
def test_postgres_run_store_save_get_list_newest_first():
    store = PostgresRunStore(TEST_DSN)
    prefix = uuid.uuid4().hex[:8]

    async def scenario():
        for i in range(3):
            await store.save(_rec(f"{prefix}-r{i}"))
        got = await store.get(f"{prefix}-r1")
        assert got is not None and got.id == f"{prefix}-r1" and got.answer == "ok"
        ids = [r.id for r in await store.list(1000)]
        assert ids.index(f"{prefix}-r2") < ids.index(f"{prefix}-r1") < ids.index(f"{prefix}-r0")
        await store.close()

    asyncio.run(scenario())


@requires_db
def test_postgres_run_store_survives_a_fresh_instance():
    """Simulates a process restart: a new store instance sees prior saves."""
    run_id = f"restart-{uuid.uuid4().hex[:8]}"

    async def scenario():
        store1 = PostgresRunStore(TEST_DSN)
        await store1.save(_rec(run_id))
        await store1.close()

        store2 = PostgresRunStore(TEST_DSN)
        got = await store2.get(run_id)
        assert got is not None and got.id == run_id
        await store2.close()

    asyncio.run(scenario())


@requires_db
def test_postgres_run_store_truncates_oversized_trace_on_save():
    store = PostgresRunStore(TEST_DSN, max_trace_events=5)
    run_id = f"big-{uuid.uuid4().hex[:8]}"
    trace = [_event(i) for i in range(50)]

    async def scenario():
        await store.save(_rec(run_id, trace=trace))
        got = await store.get(run_id)
        assert got is not None
        assert len(got.trace) == 5  # capped, not the original 50
        assert any(e.type == "sampled" for e in got.trace)
        await store.close()

    asyncio.run(scenario())


@requires_db
def test_postgres_run_store_prune_by_age_and_row_cap():
    store = PostgresRunStore(TEST_DSN)
    prefix = uuid.uuid4().hex[:8]

    async def scenario():
        for i in range(5):
            await store.save(_rec(f"{prefix}-p{i}"))
        # Rows were just inserted, so the age filter (older than
        # DEFAULT_RETENTION_DAYS) matches none of them — this exercises the
        # row-cap half of prune() deterministically: whole table trimmed to
        # its 2 newest rows, so at least our 3 oldest are gone.
        deleted = await store.prune(max_age_days=DEFAULT_RETENTION_DAYS, max_rows=2)
        assert deleted >= 3
        remaining = await store.list(1000)
        assert sum(1 for r in remaining if r.id.startswith(prefix)) <= 2
        await store.close()

    asyncio.run(scenario())


def test_default_retention_constants_are_sane():
    assert DEFAULT_RETENTION_DAYS > 0
    assert DEFAULT_RETENTION_ROWS > 0
