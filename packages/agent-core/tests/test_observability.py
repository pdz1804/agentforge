"""Token/cost accounting + run store."""

import asyncio

from agent_core import InMemoryRunStore, RunRecord, token_cost, usage_totals
from agent_core.runtime import TraceEvent


def _rec(rid: str) -> RunRecord:
    return RunRecord(id=rid, manifest_id="m", model="x", input="in", status="completed")


def test_usage_totals_sums_across_trace():
    trace = [
        TraceEvent(
            step=1, type="model", node="agent", usage={"input_tokens": 10, "output_tokens": 3}
        ),
        TraceEvent(
            step=2, type="answer", node="agent", usage={"input_tokens": 5, "output_tokens": 7}
        ),
        TraceEvent(step=2, type="tool", node="echo"),  # no usage
    ]
    assert usage_totals(trace) == {"input_tokens": 15, "output_tokens": 10}


def test_token_cost_known_and_unknown_model():
    usage = {"input_tokens": 1000, "output_tokens": 1000}
    assert token_cost(usage, "gpt-4o-mini") == round(0.00015 + 0.0006, 6)
    assert token_cost(usage, "no_such_model") == 0.0  # unknown -> free


def test_run_store_save_get_list_newest_first():
    store = InMemoryRunStore()

    async def scenario():
        for i in range(3):
            await store.save(_rec(f"r{i}"))
        got = await store.get("r1")
        assert got is not None and got.id == "r1"
        assert [r.id for r in await store.list(50)] == ["r2", "r1", "r0"]

    asyncio.run(scenario())


def test_run_store_list_zero_or_negative_limit_is_empty():
    store = InMemoryRunStore()

    async def scenario():
        await store.save(_rec("r0"))
        assert await store.list(0) == []  # -0 must not dump everything
        assert await store.list(-3) == []

    asyncio.run(scenario())


def test_run_store_is_bounded():
    store = InMemoryRunStore(max_runs=2)

    async def scenario():
        for i in range(4):
            await store.save(_rec(f"r{i}"))
        assert [r.id for r in await store.list(50)] == ["r3", "r2"]  # oldest evicted
        assert await store.get("r0") is None

    asyncio.run(scenario())
