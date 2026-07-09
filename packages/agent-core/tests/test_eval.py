"""Agent evaluation harness — the Phase 9 exit contract (PRD Section 14).

Covers: scoring modes (programmatic/rubric/llm_judge with a fake judge),
dev/held-out disjointness, an offline end-to-end suite run, and the
regression-gate diff logic.
"""

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_core import (
    AgentCoreError,
    DevHeldOutReport,
    EvalReport,
    EvalSuite,
    EvalTask,
    ManifestValidationError,
    TaskScore,
    build_default_registries,
    check_disjoint,
    check_regression,
    discover_suite_pairs,
    evaluate_pair,
    load_manifest_dict,
    load_suite_dict,
    score_llm_judge,
    score_programmatic,
    score_rubric,
)
from agent_core.eval import SuitePair

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITES_DIR = REPO_ROOT / "suites"


# --------------------------------------------------------------------------- #
# Scoring modes
# --------------------------------------------------------------------------- #
def test_score_programmatic_exact():
    task = EvalTask(
        id="t1", input="hi", scoring_mode="programmatic", match_type="exact", expected="hello"
    )
    assert score_programmatic(task, "hello").passed is True
    assert score_programmatic(task, "hello there").passed is False


def test_score_programmatic_contains():
    task = EvalTask(id="t1", input="hi", scoring_mode="programmatic", expected="orchid")
    assert score_programmatic(task, "I love the orchid garden").passed is True
    assert score_programmatic(task, "I love the daisy garden").passed is False


def test_score_programmatic_regex():
    task = EvalTask(
        id="t1", input="hi", scoring_mode="programmatic", match_type="regex", expected=r"CODE-\d+"
    )
    assert score_programmatic(task, "your code is CODE-42").passed is True
    assert score_programmatic(task, "no code here").passed is False


def test_score_programmatic_invalid_regex_raises():
    task = EvalTask(
        id="t1", input="hi", scoring_mode="programmatic", match_type="regex", expected="["
    )
    with pytest.raises(AgentCoreError):
        score_programmatic(task, "anything")


def test_score_rubric_partial_credit_and_threshold():
    task = EvalTask(
        id="t1", input="hi", scoring_mode="rubric", rubric=["orchid", "daisy"], pass_threshold=1.0
    )
    full = score_rubric(task, "I mention orchid and daisy both")
    assert full.score == 1.0 and full.passed is True

    partial = score_rubric(task, "I mention only orchid")
    assert partial.score == 0.5 and partial.passed is False  # below the 1.0 threshold

    lenient_task = task.model_copy(update={"pass_threshold": 0.5})
    lenient = score_rubric(lenient_task, "I mention only orchid")
    assert lenient.passed is True


def test_score_llm_judge_uses_injected_fake_judge_offline():
    """The judge call is injectable — no network, no API key needed."""
    task = EvalTask(
        id="t1", input="explain photosynthesis", scoring_mode="llm_judge",
        rubric=["mentions sunlight"], pass_threshold=0.6,
    )

    async def fake_judge(prompt: str) -> str:
        assert "explain photosynthesis" in prompt  # fixed prompt carries the task input
        assert "mentions sunlight" in prompt  # and the rubric criteria
        return "0.85"

    score = asyncio.run(score_llm_judge(task, "plants use sunlight", fake_judge))
    assert score.score == 0.85
    assert score.passed is True


def test_score_llm_judge_rejects_non_numeric_reply():
    task = EvalTask(id="t1", input="x", scoring_mode="llm_judge", rubric=["y"])

    async def bad_judge(prompt: str) -> str:
        return "I refuse to grade this."

    with pytest.raises(AgentCoreError):
        asyncio.run(score_llm_judge(task, "answer", bad_judge))


def test_score_llm_judge_clamps_out_of_range_score():
    task = EvalTask(id="t1", input="x", scoring_mode="llm_judge", rubric=["y"])

    async def over_judge(prompt: str) -> str:
        return "1.7"

    score = asyncio.run(score_llm_judge(task, "answer", over_judge))
    assert score.score == 1.0


def test_task_requires_expected_for_programmatic():
    with pytest.raises(ValidationError):
        EvalTask(id="t1", input="hi", scoring_mode="programmatic")


def test_task_requires_rubric_for_rubric_mode():
    with pytest.raises(ValidationError):
        EvalTask(id="t1", input="hi", scoring_mode="rubric")


# --------------------------------------------------------------------------- #
# Dev / held-out disjointness
# --------------------------------------------------------------------------- #
def _suite(suite_id: str, split: str, tasks: list[dict]) -> EvalSuite:
    return load_suite_dict(
        {"id": suite_id, "manifest_id": "demo", "split": split, "tasks": tasks}
    )


def test_disjoint_suites_pass():
    dev = _suite(
        "demo.dev", "dev",
        [{"id": "d1", "input": "alpha phrase", "scoring_mode": "programmatic",
          "expected": "alpha"}],
    )
    held = _suite(
        "demo.held_out", "held_out",
        [{"id": "h1", "input": "totally different beta text", "scoring_mode": "programmatic",
          "expected": "beta"}],
    )
    check_disjoint(dev, held)  # must not raise


def test_shared_task_id_is_rejected():
    dev = _suite(
        "demo.dev", "dev",
        [{"id": "shared", "input": "alpha phrase", "scoring_mode": "programmatic",
          "expected": "a"}],
    )
    held = _suite(
        "demo.held_out", "held_out",
        [{"id": "shared", "input": "different text entirely", "scoring_mode": "programmatic",
          "expected": "b"}],
    )
    with pytest.raises(AgentCoreError) as exc:
        check_disjoint(dev, held)
    assert "shared" in str(exc.value)


def test_near_duplicate_input_is_rejected():
    dev = _suite(
        "demo.dev", "dev",
        [{"id": "d1", "input": "please summarize the quarterly report",
          "scoring_mode": "programmatic", "expected": "x"}],
    )
    held = _suite(
        "demo.held_out", "held_out",
        # only punctuation differs from the dev input -> near-duplicate
        [{"id": "h1", "input": "please summarize the quarterly report.",
          "scoring_mode": "programmatic", "expected": "x"}],
    )
    with pytest.raises(AgentCoreError) as exc:
        check_disjoint(dev, held)
    assert "near-duplicate" in str(exc.value)


def test_mismatched_manifest_ids_are_rejected():
    dev = load_suite_dict(
        {"id": "a.dev", "manifest_id": "agent_a", "split": "dev",
         "tasks": [{"id": "d1", "input": "x", "scoring_mode": "programmatic", "expected": "x"}]}
    )
    held = load_suite_dict(
        {"id": "b.held_out", "manifest_id": "agent_b", "split": "held_out",
         "tasks": [{"id": "h1", "input": "y", "scoring_mode": "programmatic", "expected": "y"}]}
    )
    with pytest.raises(AgentCoreError):
        check_disjoint(dev, held)


def test_duplicate_task_id_within_one_suite_is_rejected():
    with pytest.raises(ManifestValidationError):
        load_suite_dict(
            {
                "id": "demo.dev", "manifest_id": "demo", "split": "dev",
                "tasks": [
                    {"id": "dup", "input": "a", "scoring_mode": "programmatic", "expected": "a"},
                    {"id": "dup", "input": "b", "scoring_mode": "programmatic", "expected": "b"},
                ],
            }
        )


# --------------------------------------------------------------------------- #
# Offline end-to-end suite run (echo model — deterministic, no API key)
# --------------------------------------------------------------------------- #
def _echo_manifest() -> dict:
    return {
        "id": "echo_agent",
        "model": {"provider": "echo", "name": "test-model"},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": [],
    }


def _echo_pair() -> SuitePair:
    dev = _suite(
        "echo.dev", "dev",
        [
            {"id": "d1", "input": "hello dev", "scoring_mode": "programmatic",
             "match_type": "exact", "expected": "hello dev"},
        ],
    )
    dev = dev.model_copy(update={"manifest_id": "echo_agent"})
    held = _suite(
        "echo.held_out", "held_out",
        [
            {"id": "h1", "input": "hello held out world", "scoring_mode": "programmatic",
             "match_type": "exact", "expected": "hello held out world"},
        ],
    )
    held = held.model_copy(update={"manifest_id": "echo_agent"})
    return SuitePair(group_id="echo", manifest_id="echo_agent", dev=dev, held_out=held)


def test_evaluate_pair_end_to_end_offline():
    registries = build_default_registries()
    manifest = load_manifest_dict(_echo_manifest())
    pair = _echo_pair()

    report = asyncio.run(evaluate_pair(manifest, registries, pair, measure_flake=True))

    assert isinstance(report, DevHeldOutReport)
    assert report.dev.pass_rate == 1.0  # echo model echoes the input verbatim
    assert report.held_out.pass_rate == 1.0
    assert report.dev.flake_rate == 0.0  # echo model is deterministic -> no flakes
    assert report.overfitting_flag is False


def test_evaluate_pair_rejects_manifest_id_mismatch():
    registries = build_default_registries()
    manifest = load_manifest_dict({**_echo_manifest(), "id": "other_id"})
    pair = _echo_pair()
    with pytest.raises(AgentCoreError):
        asyncio.run(evaluate_pair(manifest, registries, pair))


# --------------------------------------------------------------------------- #
# Regression gate
# --------------------------------------------------------------------------- #
def _report(pass_rate: float, task_results: list[tuple[str, bool]]) -> EvalReport:
    scores = [
        TaskScore(task_id=tid, score=1.0 if ok else 0.0, passed=ok) for tid, ok in task_results
    ]
    return EvalReport(
        suite_id="s", manifest_id="demo", split="held_out", task_scores=scores,
        pass_rate=pass_rate, mean_score=pass_rate, flake_rate=0.0,
    )


def _dev_held_out(held_out: EvalReport, dev_pass_rate: float = 1.0) -> DevHeldOutReport:
    dev = _report(dev_pass_rate, [("d1", True)])
    return DevHeldOutReport(
        manifest_id="demo", dev=dev, held_out=held_out,
        overfitting_gap=dev.pass_rate - held_out.pass_rate,
        overfitting_flag=(dev.pass_rate - held_out.pass_rate) > 0.2,
    )


def test_regression_gate_blocks_on_held_out_drop_beyond_tolerance():
    baseline = _report(1.0, [("t1", True), ("t2", True)])
    current = _dev_held_out(_report(0.5, [("t1", True), ("t2", False)]))

    result = check_regression(current, baseline, tolerance=0.05)

    assert result.blocked is True
    assert result.delta == pytest.approx(-0.5)
    assert result.newly_failing_tasks == ["t2"]
    assert result.newly_passing_tasks == []


def test_regression_gate_allows_drop_within_tolerance():
    baseline = _report(0.80, [("t1", True), ("t2", True), ("t3", True), ("t4", False)])
    # A ~0.02 drop is comfortably within a 0.05 tolerance -> not blocked.
    slightly_worse = _report(0.78, [("t1", True), ("t2", True), ("t3", False), ("t4", False)])
    current = _dev_held_out(slightly_worse)

    result = check_regression(current, baseline, tolerance=0.05)

    assert result.blocked is False
    assert result.newly_failing_tasks == ["t3"]


def test_discover_suite_pairs_from_tmp_dir(tmp_path):
    (tmp_path / "demo.dev.yaml").write_text(
        "id: demo.dev\nmanifest_id: demo\nsplit: dev\ntasks:\n"
        "  - id: d1\n    input: alpha phrase\n    scoring_mode: programmatic\n"
        "    expected: alpha\n",
        encoding="utf-8",
    )
    (tmp_path / "demo.held_out.yaml").write_text(
        "id: demo.held_out\nmanifest_id: demo\nsplit: held_out\ntasks:\n"
        "  - id: h1\n    input: totally different beta text\n    scoring_mode: programmatic\n"
        "    expected: beta\n",
        encoding="utf-8",
    )
    pairs = discover_suite_pairs(tmp_path)
    assert set(pairs) == {"demo"}
    assert pairs["demo"].manifest_id == "demo"
    assert len(pairs["demo"].dev.tasks) == 1
    assert len(pairs["demo"].held_out.tasks) == 1


def test_discover_suite_pairs_missing_split_raises(tmp_path):
    (tmp_path / "demo.dev.yaml").write_text(
        "id: demo.dev\nmanifest_id: demo\nsplit: dev\ntasks:\n"
        "  - id: d1\n    input: alpha\n    scoring_mode: programmatic\n    expected: alpha\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestValidationError):
        discover_suite_pairs(tmp_path)


def test_discover_suite_pairs_on_missing_dir_returns_empty():
    assert discover_suite_pairs(SUITES_DIR / "does_not_exist") == {}


def test_sample_echo_agent_suite_pair_loads_and_is_disjoint():
    """The real suites/echo_agent.{dev,held_out}.yaml files ship as a working example."""
    pairs = discover_suite_pairs(SUITES_DIR)
    assert "echo_agent" in pairs
    pair = pairs["echo_agent"]
    assert pair.manifest_id == "echo_agent"
    assert len(pair.dev.tasks) >= 1
    assert len(pair.held_out.tasks) >= 1


def test_regression_gate_flags_dev_only_gains():
    baseline_held_out = _report(0.5, [("t1", True), ("t2", False)])
    baseline_dev = _report(0.5, [("d1", True), ("d2", False)])
    # Dev pass rate jumps to 1.0 but held-out stays flat -> classic overfitting signal.
    current = _dev_held_out(_report(0.5, [("t1", True), ("t2", False)]), dev_pass_rate=1.0)

    result = check_regression(current, baseline_held_out, baseline_dev=baseline_dev, tolerance=0.05)

    assert result.blocked is False  # held-out didn't regress
    assert result.dev_only_gain_flagged is True
