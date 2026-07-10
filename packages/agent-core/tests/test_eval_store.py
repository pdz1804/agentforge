"""Eval report + baseline persistence (Gap G5)."""

import asyncio

from agent_core import (
    InMemoryEvalReportStore,
    StoredBaseline,
    select_eval_report_store,
)
from agent_core.eval import DevHeldOutReport, EvalReport, TaskScore


def _report(pass_rate: float = 1.0) -> DevHeldOutReport:
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


def test_save_and_fetch_report():
    store = InMemoryEvalReportStore()

    async def scenario():
        stored = await store.save_report("rep1", _report())
        assert stored.id == "rep1"
        assert stored.manifest_id == "agent_a"
        fetched = await store.get_report("rep1")
        assert fetched is not None and fetched.report.held_out.pass_rate == 1.0
        assert await store.get_report("missing") is None

    asyncio.run(scenario())


def test_set_and_get_baseline_overwrites():
    store = InMemoryEvalReportStore()

    async def scenario():
        assert await store.get_baseline("agent_a") is None
        report = _report(pass_rate=1.0)
        await store.set_baseline(
            StoredBaseline(
                manifest_id="agent_a",
                held_out=report.held_out,
                dev=report.dev,
                source_report_id="rep1",
            )
        )
        got = await store.get_baseline("agent_a")
        assert got is not None and got.held_out.pass_rate == 1.0
        # Promoting again overwrites.
        report2 = _report(pass_rate=0.5)
        await store.set_baseline(
            StoredBaseline(manifest_id="agent_a", held_out=report2.held_out)
        )
        assert (await store.get_baseline("agent_a")).held_out.pass_rate == 0.5

    asyncio.run(scenario())


def test_select_eval_report_store_defaults_to_in_memory():
    assert isinstance(select_eval_report_store(), InMemoryEvalReportStore)
