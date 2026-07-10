"""Per-user data isolation scaffold: owner-scoped reads/writes on the three
stores (RunStore, ManifestStore, EvalReportStore).

In-memory backend cases always run (no DB). Postgres-gated cases for
RunStore's owner column mirror test_postgres_run_store.py's skip condition —
the controller runs those live; they skip cleanly on a machine with no
reachable Postgres.
"""

import asyncio
import os
import uuid

import pytest

from agent_core import (
    InMemoryEvalReportStore,
    InMemoryManifestStore,
    InMemoryRunStore,
    RunRecord,
    StoredBaseline,
)
from agent_core.eval import DevHeldOutReport, EvalReport, TaskScore
from agent_core.observability import PostgresRunStore, postgres_reachable

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


def _rec(rid: str) -> RunRecord:
    return RunRecord(id=rid, manifest_id="m", model="x", input="in", status="completed")


def _manifest(temp: float = 0.2) -> dict:
    return {
        "id": "agent_a",
        "model": {"provider": "echo", "name": "test-model", "temperature": temp},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": [],
    }


def _eval_report(pass_rate: float = 1.0) -> DevHeldOutReport:
    def split(suite_id: str, split_name: str) -> EvalReport:
        return EvalReport(
            suite_id=suite_id,
            manifest_id="agent_a",
            split=split_name,
            task_scores=[TaskScore(task_id="t1", score=pass_rate, passed=pass_rate >= 1.0)],
            pass_rate=pass_rate,
            mean_score=pass_rate,
            flake_rate=0.0,
        )

    return DevHeldOutReport(
        manifest_id="agent_a",
        dev=split("agent_a.dev", "dev"),
        held_out=split("agent_a.held_out", "held_out"),
        overfitting_gap=0.0,
        overfitting_flag=False,
    )


# --------------------------------------------------------------------------- #
# RunStore (in-memory)
# --------------------------------------------------------------------------- #
def test_run_store_default_owner_is_public():
    store = InMemoryRunStore()

    async def scenario():
        await store.save(_rec("r0"))
        got = await store.get("r0")
        assert got is not None and got.owner == "public"

    asyncio.run(scenario())


def test_run_store_save_and_list_scoped_by_owner():
    store = InMemoryRunStore()

    async def scenario():
        await store.save(_rec("a1"), owner="alice")
        await store.save(_rec("a2"), owner="alice")
        await store.save(_rec("b1"), owner="bob")

        alice_runs = await store.list(50, owner="alice")
        assert {r.id for r in alice_runs} == {"a1", "a2"}

        bob_runs = await store.list(50, owner="bob")
        assert {r.id for r in bob_runs} == {"b1"}

        # Back-compat: owner=None (the default) sees everything, unfiltered.
        all_runs = await store.list(50)
        assert {r.id for r in all_runs} == {"a1", "a2", "b1"}

    asyncio.run(scenario())


def test_run_store_get_scoped_by_owner_hides_other_owners_run():
    store = InMemoryRunStore()

    async def scenario():
        await store.save(_rec("a1"), owner="alice")

        assert (await store.get("a1", owner="alice")) is not None
        assert (await store.get("a1", owner="bob")) is None
        # Unscoped get (owner=None, the default) is unaffected.
        assert (await store.get("a1")) is not None

    asyncio.run(scenario())


def test_run_store_list_respects_limit_within_owner_scope():
    store = InMemoryRunStore()

    async def scenario():
        for i in range(3):
            await store.save(_rec(f"a{i}"), owner="alice")
        await store.save(_rec("b0"), owner="bob")

        limited = await store.list(1, owner="alice")
        assert len(limited) == 1
        assert limited[0].id == "a2"  # newest alice run

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# ManifestStore (in-memory)
# --------------------------------------------------------------------------- #
def test_manifest_store_default_owner_is_public():
    store = InMemoryManifestStore()

    async def scenario():
        record = await store.save("agent_a", _manifest())
        assert record.owner == "public"

    asyncio.run(scenario())


def test_manifest_store_save_and_list_scoped_by_owner():
    store = InMemoryManifestStore()

    async def scenario():
        await store.save("alice_agent", _manifest(), owner="alice")
        await store.save("bob_agent", _manifest(), owner="bob")

        assert await store.list_ids(owner="alice") == ["alice_agent"]
        assert await store.list_ids(owner="bob") == ["bob_agent"]
        # Back-compat: owner=None (the default) sees every id, unfiltered.
        assert set(await store.list_ids()) == {"alice_agent", "bob_agent"}

    asyncio.run(scenario())


def test_manifest_store_get_scoped_by_owner_hides_other_owners_manifest():
    store = InMemoryManifestStore()

    async def scenario():
        await store.save("alice_agent", _manifest(), owner="alice")

        assert (await store.get("alice_agent", owner="alice")) is not None
        assert (await store.get("alice_agent", owner="bob")) is None
        # Unscoped get (owner=None, the default) is unaffected.
        assert (await store.get("alice_agent")) is not None

    asyncio.run(scenario())


def test_manifest_store_list_versions_scoped_by_owner():
    store = InMemoryManifestStore()

    async def scenario():
        await store.save("agent_a", _manifest(0.1), owner="alice")
        await store.save("agent_a", _manifest(0.2), owner="alice")

        versions = await store.list_versions("agent_a", owner="alice")
        assert [v.version for v in versions] == [1, 2]

        assert await store.list_versions("agent_a", owner="bob") == []
        # Back-compat: owner=None (the default) sees every version, unfiltered.
        assert len(await store.list_versions("agent_a")) == 2

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# EvalReportStore (in-memory)
# --------------------------------------------------------------------------- #
def test_eval_report_store_default_owner_is_public():
    store = InMemoryEvalReportStore()

    async def scenario():
        stored = await store.save_report("rep1", _eval_report())
        assert stored.owner == "public"

    asyncio.run(scenario())


def test_eval_report_store_get_scoped_by_owner():
    store = InMemoryEvalReportStore()

    async def scenario():
        await store.save_report("rep_alice", _eval_report(), owner="alice")
        await store.save_report("rep_bob", _eval_report(), owner="bob")

        assert (await store.get_report("rep_alice", owner="alice")) is not None
        assert (await store.get_report("rep_alice", owner="bob")) is None
        # Back-compat: owner=None (the default) is unaffected.
        assert (await store.get_report("rep_alice")) is not None

    asyncio.run(scenario())


def test_eval_report_store_baseline_scoped_by_owner():
    store = InMemoryEvalReportStore()

    async def scenario():
        report = _eval_report()
        await store.set_baseline(
            StoredBaseline(manifest_id="agent_a", held_out=report.held_out), owner="alice"
        )

        assert (await store.get_baseline("agent_a", owner="alice")) is not None
        assert (await store.get_baseline("agent_a", owner="bob")) is None
        # Back-compat: owner=None (the default) is unaffected.
        assert (await store.get_baseline("agent_a")) is not None

    asyncio.run(scenario())


def test_eval_baseline_cannot_be_clobbered_across_owners():
    # A second owner promoting a baseline for the SAME (caller-controlled)
    # manifest id must not destroy the first owner's baseline.
    store = InMemoryEvalReportStore()

    async def scenario():
        report = _eval_report()
        await store.set_baseline(
            StoredBaseline(manifest_id="shared", held_out=report.held_out), owner="alice"
        )
        await store.set_baseline(
            StoredBaseline(manifest_id="shared", held_out=report.held_out), owner="bob"
        )
        alice_baseline = await store.get_baseline("shared", owner="alice")
        assert alice_baseline is not None and alice_baseline.owner == "alice"
        bob_baseline = await store.get_baseline("shared", owner="bob")
        assert bob_baseline is not None and bob_baseline.owner == "bob"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# RunStore (Postgres) — owner column. Requires a real Postgres; skipped
# cleanly otherwise (same DSN/skip convention as test_postgres_run_store.py).
# --------------------------------------------------------------------------- #
@requires_db
def test_postgres_run_store_save_and_list_scoped_by_owner():
    store = PostgresRunStore(TEST_DSN)
    prefix = uuid.uuid4().hex[:8]

    async def scenario():
        await store.save(_rec(f"{prefix}-a1"), owner="alice")
        await store.save(_rec(f"{prefix}-b1"), owner="bob")

        alice_runs = await store.list(1000, owner="alice")
        assert any(r.id == f"{prefix}-a1" for r in alice_runs)
        assert all(r.id != f"{prefix}-b1" for r in alice_runs)

        got_as_bob = await store.get(f"{prefix}-a1", owner="bob")
        assert got_as_bob is None
        got_as_alice = await store.get(f"{prefix}-a1", owner="alice")
        assert got_as_alice is not None and got_as_alice.owner == "alice"

        await store.close()

    asyncio.run(scenario())


@requires_db
def test_postgres_run_store_owner_defaults_to_public():
    store = PostgresRunStore(TEST_DSN)
    run_id = f"pub-{uuid.uuid4().hex[:8]}"

    async def scenario():
        await store.save(_rec(run_id))
        got = await store.get(run_id)
        assert got is not None and got.owner == "public"
        await store.close()

    asyncio.run(scenario())


@requires_db
def test_postgres_run_store_alter_table_migration_is_idempotent():
    # Simulates a pre-existing table: create it WITHOUT the owner column
    # (dropping first for a clean slate), then confirm a fresh store's
    # _ensure_pool migrates it via ADD COLUMN IF NOT EXISTS without error and
    # without disturbing existing rows.
    import asyncpg

    async def scenario():
        conn = await asyncpg.connect(TEST_DSN)
        try:
            await conn.execute("DROP TABLE IF EXISTS runs")
            await conn.execute(
                """
                CREATE TABLE runs (
                    id TEXT PRIMARY KEY,
                    manifest_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input TEXT NOT NULL,
                    status TEXT NOT NULL,
                    answer TEXT,
                    trace JSONB NOT NULL,
                    usage JSONB NOT NULL,
                    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            pre_migration_id = f"legacy-{uuid.uuid4().hex[:8]}"
            await conn.execute(
                """
                INSERT INTO runs (id, manifest_id, model, input, status, trace, usage, created_at)
                VALUES ($1, 'm', 'x', 'in', 'completed', '[]'::jsonb, '{}'::jsonb, '')
                """,
                pre_migration_id,
            )
        finally:
            await conn.close()

        store = PostgresRunStore(TEST_DSN)
        got = await store.get(pre_migration_id)
        assert got is not None
        assert got.owner == "public"  # pre-existing row backfilled by the DEFAULT
        await store.close()

    asyncio.run(scenario())
