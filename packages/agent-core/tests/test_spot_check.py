"""LLM-judge human spot-check hook (PRD Section 14.2, Gap G2).

Judged tasks are surfaced for periodic human audit. The feature is strictly
additive: only ``llm_judge`` tasks yield samples, and the sample collection is
derived from an already-produced report rather than changing scoring output.
"""

import asyncio

from agent_core import (
    EvalSuite,
    InMemoryEvalReportStore,
    SpotCheckSample,
    build_default_registries,
    collect_spot_check_samples,
    compile_agent,
    load_manifest_dict,
    run_suite,
)


def _echo_manifest() -> dict:
    return {
        "id": "echo_agent",
        "model": {"provider": "echo", "name": "test-model"},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": [],
    }


def _judge_suite() -> EvalSuite:
    return EvalSuite.model_validate(
        {
            "id": "judged.dev",
            "manifest_id": "echo_agent",
            "split": "dev",
            "tasks": [
                {
                    "id": "j1",
                    "input": "describe an orchid",
                    "scoring_mode": "llm_judge",
                    "rubric": ["mentions petals"],
                    "pass_threshold": 0.6,
                },
                {
                    "id": "p1",
                    "input": "hello world",
                    "scoring_mode": "programmatic",
                    "match_type": "exact",
                    "expected": "hello world",
                },
            ],
        }
    )


def test_collect_spot_check_samples_only_for_judge_tasks():
    registries = build_default_registries()
    agent = compile_agent(load_manifest_dict(_echo_manifest()), registries)
    suite = _judge_suite()

    async def fake_judge(prompt: str) -> str:
        assert "describe an orchid" in prompt  # judged task's input reaches the judge
        return "0.9"

    report = asyncio.run(run_suite(agent, suite, judge_fn=fake_judge, measure_flake=False))
    samples = collect_spot_check_samples(suite, report)

    # Only the llm_judge task produces a sample; the programmatic task does not.
    assert [s.task_id for s in samples] == ["j1"]
    sample = samples[0]
    assert sample.suite_id == "judged.dev"
    assert sample.split == "dev"
    assert sample.input == "describe an orchid"
    assert sample.judge_score == 0.9
    assert sample.passed is True
    assert sample.review_status == "needs_review"  # starts in the audit queue
    assert "0.9" in sample.judge_detail  # judge's raw verdict is retained


def test_collect_spot_check_samples_empty_without_judge_tasks():
    registries = build_default_registries()
    agent = compile_agent(load_manifest_dict(_echo_manifest()), registries)
    suite = EvalSuite.model_validate(
        {
            "id": "prog.dev",
            "manifest_id": "echo_agent",
            "split": "dev",
            "tasks": [
                {
                    "id": "p1",
                    "input": "hello world",
                    "scoring_mode": "programmatic",
                    "match_type": "exact",
                    "expected": "hello world",
                }
            ],
        }
    )
    report = asyncio.run(run_suite(agent, suite, measure_flake=False))
    assert collect_spot_check_samples(suite, report) == []


def test_store_round_trips_spot_check_samples():
    store = InMemoryEvalReportStore()

    async def scenario():
        assert await store.get_spot_check("rep1") == []  # unknown id -> empty
        sample = SpotCheckSample(
            task_id="j1",
            suite_id="judged.dev",
            split="dev",
            input="describe an orchid",
            answer="an orchid has petals",
            judge_score=0.9,
            passed=True,
            judge_detail="llm_judge raw_response='0.9'",
        )
        await store.save_spot_check("rep1", [sample])
        got = await store.get_spot_check("rep1")
        assert len(got) == 1 and got[0].task_id == "j1"

    asyncio.run(scenario())
