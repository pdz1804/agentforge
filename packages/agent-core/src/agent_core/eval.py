"""Agent evaluation harness (PRD Section 14, Epic H / Phase 9).

The LLM analog of train/dev/held-out testing. Because there is no gradient
training in this system, "validation/testing" means dev/held-out *evaluation*
of a compiled agent against a fixed task suite:

- An ``EvalSuite`` is one split's worth of tasks for one manifest (PRD Section
  14.1). A manifest's full evaluation is a *pair* of suites (``dev`` +
  ``held_out``) that share a ``manifest_id`` and must be disjoint (checked by
  task id and near-duplicate input, per the leakage rule).
- Each task is scored by exactly one of three modes (Section 14.2):
  ``programmatic`` (exact/contains/regex), ``rubric`` (keyword/criteria
  checklist), or ``llm_judge`` (a fixed judge prompt sent to an injectable
  judge function so tests never make a live model call).
- Runs use the runtime's ``eval_mode=True`` (temperature 0, memory-isolated)
  and are repeated once per task to surface a flake indicator (Section 14.3).
- A regression gate (Epic H5) compares a fresh dev+held-out report against a
  stored baseline and blocks promotion when the held-out pass rate regresses
  beyond tolerance, showing the per-task diff.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import AgentCoreError, ManifestValidationError
from .interfaces import Message, ModelProvider
from .registry import Registries
from .runtime import compile_agent
from .schema import AgentManifest

_STRICT = ConfigDict(extra="forbid")

# A dev/held-out gap beyond this is flagged as "dev-only gains" overfitting
# (PRD Section 14.1: "a large dev >> held-out gap signals overfitting").
_OVERFIT_GAP_THRESHOLD = 0.2

# Two tasks with normalized-input similarity at/above this are treated as
# near-duplicates for the leakage check (Section 14.1's disjointness rule).
_NEAR_DUP_THRESHOLD = 0.9


# --------------------------------------------------------------------------- #
# Suite schema
# --------------------------------------------------------------------------- #
class ScoringMode(StrEnum):
    programmatic = "programmatic"
    rubric = "rubric"
    llm_judge = "llm_judge"


class Split(StrEnum):
    dev = "dev"
    held_out = "held_out"


class MatchType(StrEnum):
    """How ``programmatic`` scoring compares the answer to ``expected``."""

    exact = "exact"
    contains = "contains"
    regex = "regex"


class EvalTask(BaseModel):
    """One evaluation task: an input, and how to score the agent's answer."""

    model_config = _STRICT

    id: str
    input: str
    scoring_mode: ScoringMode
    expected: str | None = None  # required for programmatic
    match_type: MatchType = MatchType.contains
    rubric: list[str] = Field(default_factory=list)  # required (non-empty) for rubric/llm_judge
    judge_prompt: str | None = None  # extra grading instructions for llm_judge
    pass_threshold: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_scoring_fields(self) -> EvalTask:
        if self.scoring_mode == ScoringMode.programmatic and self.expected is None:
            raise ValueError(f"task '{self.id}': scoring_mode=programmatic requires 'expected'")
        if self.scoring_mode == ScoringMode.rubric and not self.rubric:
            raise ValueError(f"task '{self.id}': scoring_mode=rubric requires a non-empty 'rubric'")
        if (
            self.scoring_mode == ScoringMode.llm_judge
            and not self.rubric
            and not self.judge_prompt
        ):
            raise ValueError(
                f"task '{self.id}': scoring_mode=llm_judge requires 'rubric' criteria and/or "
                "'judge_prompt' instructions"
            )
        return self


class EvalSuite(BaseModel):
    """One split (dev or held-out) of tasks for a single manifest."""

    model_config = _STRICT

    id: str
    manifest_id: str
    tasks: list[EvalTask]
    split: Split

    @model_validator(mode="after")
    def _check_unique_task_ids(self) -> EvalSuite:
        ids = [t.id for t in self.tasks]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"suite '{self.id}': duplicate task id(s) {sorted(dupes)}")
        return self


class SuitePair(BaseModel):
    """A manifest's dev + held-out suites, grouped for one evaluation run."""

    model_config = _STRICT

    group_id: str
    manifest_id: str
    dev: EvalSuite
    held_out: EvalSuite


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_suite_dict(data: dict[str, Any]) -> EvalSuite:
    """Validate a mapping into an ``EvalSuite`` (mirrors ``load_manifest_dict``)."""
    try:
        return EvalSuite.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError, or the model_validators above
        raise ManifestValidationError(f"invalid eval suite: {exc}") from exc


def load_suite_file(path: str | Path) -> EvalSuite:
    """Load and validate a YAML or JSON suite file."""
    p = Path(path)
    if not p.exists():
        raise ManifestValidationError(f"suite file not found: {p}")
    text = p.read_text(encoding="utf-8")
    data = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ManifestValidationError(f"suite {p} must be a mapping")
    return load_suite_dict(data)


def discover_suite_pairs(suites_dir: str | Path) -> dict[str, SuitePair]:
    """Load every suite file under ``suites_dir`` and pair dev with held-out.

    File naming convention: ``<group_id>.dev.(yaml|yml|json)`` and
    ``<group_id>.held_out.(yaml|yml|json)``. Each discovered pair is
    disjointness-checked (``check_disjoint``) before being returned, so a
    leaking suite pair fails to load rather than being silently usable.
    Returns ``{}`` if the directory does not exist (no suites configured yet).
    """
    base = Path(suites_dir)
    by_group: dict[str, dict[str, EvalSuite]] = {}
    if base.exists():
        for path in sorted(base.iterdir()):
            if path.suffix not in (".yaml", ".yml", ".json"):
                continue
            stem = path.stem
            if stem.endswith(".dev"):
                group, split = stem[: -len(".dev")], "dev"
            elif stem.endswith(".held_out"):
                group, split = stem[: -len(".held_out")], "held_out"
            else:
                continue  # not a recognized suite file; skip silently
            suite = load_suite_file(path)
            if suite.split.value != split:
                raise ManifestValidationError(
                    f"suite file '{path.name}' name implies split='{split}' but the "
                    f"file declares split='{suite.split.value}'"
                )
            by_group.setdefault(group, {})[split] = suite

    pairs: dict[str, SuitePair] = {}
    for group, splits in by_group.items():
        missing = {"dev", "held_out"} - set(splits)
        if missing:
            raise ManifestValidationError(
                f"suite group '{group}' is missing split(s): {sorted(missing)}"
            )
        dev, held_out = splits["dev"], splits["held_out"]
        check_disjoint(dev, held_out)
        pairs[group] = SuitePair(
            group_id=group, manifest_id=dev.manifest_id, dev=dev, held_out=held_out
        )
    return pairs


# --------------------------------------------------------------------------- #
# Disjointness (leakage) check
# --------------------------------------------------------------------------- #
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip().lower())


def check_disjoint(
    dev: EvalSuite, held_out: EvalSuite, *, near_dup_threshold: float = _NEAR_DUP_THRESHOLD
) -> None:
    """Enforce PRD Section 14.1's leakage rule: dev and held-out must share no
    task id and no near-duplicate input. Raises ``AgentCoreError`` listing
    every violation found (not just the first).
    """
    if dev.manifest_id != held_out.manifest_id:
        raise AgentCoreError(
            f"dev suite '{dev.id}' (manifest_id='{dev.manifest_id}') and held_out suite "
            f"'{held_out.id}' (manifest_id='{held_out.manifest_id}') target different manifests"
        )

    violations: list[str] = []
    dev_ids = {t.id for t in dev.tasks}
    held_out_ids = {t.id for t in held_out.tasks}
    shared_ids = dev_ids & held_out_ids
    if shared_ids:
        violations.append(f"task id(s) present in both splits: {sorted(shared_ids)}")

    dev_inputs = [(t.id, _normalize(t.input)) for t in dev.tasks]
    held_inputs = [(t.id, _normalize(t.input)) for t in held_out.tasks]
    for dev_id, dev_norm in dev_inputs:
        for held_id, held_norm in held_inputs:
            ratio = difflib.SequenceMatcher(None, dev_norm, held_norm).ratio()
            if ratio >= near_dup_threshold:
                violations.append(
                    f"near-duplicate input between dev '{dev_id}' and held_out '{held_id}' "
                    f"(similarity={ratio:.2f})"
                )

    if violations:
        raise AgentCoreError(
            f"dev/held-out leakage between '{dev.id}' and '{held_out.id}': "
            + "; ".join(violations)
        )


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
class TaskScore(BaseModel):
    """The result of scoring one task's answer."""

    model_config = _STRICT

    task_id: str
    score: float
    passed: bool
    detail: str = ""
    answer: str | None = None
    flake: bool = False  # True if a same-input rerun disagreed on pass/fail


def score_programmatic(task: EvalTask, answer: str) -> TaskScore:
    """Exact/contains/regex match against ``task.expected`` (deterministic)."""
    answer = answer or ""
    expected = task.expected or ""
    if task.match_type == MatchType.exact:
        passed = answer.strip() == expected.strip()
    elif task.match_type == MatchType.regex:
        try:
            passed = re.search(expected, answer) is not None
        except re.error as exc:
            raise AgentCoreError(f"task '{task.id}': invalid regex '{expected}': {exc}") from exc
    else:
        passed = expected in answer
    return TaskScore(
        task_id=task.id,
        score=1.0 if passed else 0.0,
        passed=passed,
        answer=answer,
        detail=f"{task.match_type.value} match against expected={expected!r}",
    )


def score_rubric(task: EvalTask, answer: str) -> TaskScore:
    """Fraction of rubric keywords/criteria present (case-insensitive) in the answer."""
    answer_lower = (answer or "").lower()
    matched = [c for c in task.rubric if c.lower() in answer_lower]
    missing = [c for c in task.rubric if c not in matched]
    score = len(matched) / len(task.rubric) if task.rubric else 0.0
    passed = score >= task.pass_threshold
    detail = f"matched {len(matched)}/{len(task.rubric)} criteria"
    if missing:
        detail += f"; missing: {missing}"
    return TaskScore(task_id=task.id, score=score, passed=passed, answer=answer, detail=detail)


# A judge function takes the fully-rendered fixed judge prompt and returns the
# judge model's raw text reply (expected to contain a single 0..1 score). Kept
# as a plain injectable callable so tests supply a fake and never hit a
# network — the ONLY place a real model call happens is `make_model_judge_fn`.
JudgeFn = Callable[[str], Awaitable[str]]

# Fixed judge prompt (PRD Section 14.2: "fixed judge prompt + model, temp 0").
# Never edited per-task beyond the task's own input/criteria/answer — a stable
# grading rubric is what keeps the judge comparable across runs.
_JUDGE_PROMPT_TEMPLATE = (
    "You are grading an AI agent's answer against a fixed rubric. "
    "Score strictly from 0.0 (fails every criterion) to 1.0 (fully satisfies all criteria), "
    "using ONLY the criteria listed below. Respond with a single number and nothing else.\n\n"
    "Task input:\n{input}\n\n"
    "Grading criteria:\n{criteria}\n\n"
    "Candidate answer:\n{answer}\n\n"
    "Score:"
)


def render_judge_prompt(task: EvalTask, answer: str) -> str:
    """Build the fixed judge prompt for one task. Exposed so tests/UI can
    display exactly what the judge sees.
    """
    criteria_lines = [f"- {c}" for c in task.rubric]
    if task.judge_prompt:
        criteria_lines.append(f"- {task.judge_prompt}")
    criteria = "\n".join(criteria_lines) or "(none specified)"
    return _JUDGE_PROMPT_TEMPLATE.format(input=task.input, criteria=criteria, answer=answer or "")


def _parse_judge_score(raw: str) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        raise AgentCoreError(f"llm judge returned a non-numeric score: {raw!r}")
    return max(0.0, min(1.0, float(match.group(0))))


async def score_llm_judge(task: EvalTask, answer: str, judge_fn: JudgeFn) -> TaskScore:
    """Score via the injectable judge function. Offline-testable: pass a fake
    ``judge_fn`` (e.g. ``lambda prompt: "0.9"``) in tests.
    """
    prompt = render_judge_prompt(task, answer)
    raw = await judge_fn(prompt)
    score = _parse_judge_score(raw)
    passed = score >= task.pass_threshold
    return TaskScore(
        task_id=task.id, score=score, passed=passed, answer=answer,
        detail=f"llm_judge raw_response={raw!r}",
    )


def make_model_judge_fn(
    provider: ModelProvider, *, model: str, temperature: float = 0.0
) -> JudgeFn:
    """Wrap a real ``ModelProvider`` as a ``JudgeFn``: fixed model, temperature=0
    (PRD Section 14.2). This is the one place a live judge call happens;
    production code wires this in, tests inject a fake ``JudgeFn`` instead.
    """

    async def _judge(prompt: str) -> str:
        resp = await provider.complete(
            [Message(role="user", content=prompt)],
            tools=None,
            model=model,
            temperature=temperature,
        )
        return resp.text

    return _judge


async def score_task(task: EvalTask, answer: str, judge_fn: JudgeFn | None) -> TaskScore:
    """Dispatch to the scoring mode named on the task."""
    if task.scoring_mode == ScoringMode.programmatic:
        return score_programmatic(task, answer)
    if task.scoring_mode == ScoringMode.rubric:
        return score_rubric(task, answer)
    if judge_fn is None:
        raise AgentCoreError(
            f"task '{task.id}' needs scoring_mode=llm_judge but no judge_fn was provided"
        )
    return await score_llm_judge(task, answer, judge_fn)


# --------------------------------------------------------------------------- #
# Running a suite
# --------------------------------------------------------------------------- #
class EvalReport(BaseModel):
    """Per-task scores + aggregate for one split (dev or held-out)."""

    model_config = _STRICT

    suite_id: str
    manifest_id: str
    split: Split
    task_scores: list[TaskScore]
    pass_rate: float
    mean_score: float
    flake_rate: float


class DevHeldOutReport(BaseModel):
    """A manifest's full evaluation: dev + held-out side by side."""

    model_config = _STRICT

    manifest_id: str
    dev: EvalReport
    held_out: EvalReport
    overfitting_gap: float  # dev.pass_rate - held_out.pass_rate
    overfitting_flag: bool  # gap beyond _OVERFIT_GAP_THRESHOLD


async def run_task(agent: Any, task: EvalTask, judge_fn: JudgeFn | None) -> TaskScore:
    """Run one task in deterministic eval mode and score the answer.

    A run-time failure (timeout, model/tool error) scores as a clean 0/failed
    task rather than raising — one broken task must not abort the whole suite.
    """
    try:
        result = await agent.arun(task.input, eval_mode=True, thread_id=f"eval-{task.id}")
    except AgentCoreError as exc:
        return TaskScore(task_id=task.id, score=0.0, passed=False, detail=f"run error: {exc}")
    # Scoring must be isolated too: a bad regex (score_programmatic), a
    # non-numeric judge reply (_parse_judge_score), or a judge-provider failure
    # raises out of score_task — and one malformed task must not abort the whole
    # suite. Catch broadly here and record it as a clean 0/failed task.
    try:
        return await score_task(task, result.answer or "", judge_fn)
    except Exception as exc:  # noqa: BLE001 — deliberate per-task isolation
        return TaskScore(task_id=task.id, score=0.0, passed=False, detail=f"scoring error: {exc}")


async def run_suite(
    agent: Any,
    suite: EvalSuite,
    *,
    judge_fn: JudgeFn | None = None,
    measure_flake: bool = True,
) -> EvalReport:
    """Run every task in ``suite`` and aggregate pass rate / mean score.

    When ``measure_flake`` is set (default), each task is run twice in eval
    mode (temp=0, memory-isolated); a disagreement between the two runs marks
    that task as flaky and contributes to the suite's ``flake_rate`` (PRD
    Section 14.3 target: < 5%).
    """
    scores: list[TaskScore] = []
    flakes = 0
    for task in suite.tasks:
        score = await run_task(agent, task, judge_fn)
        if measure_flake:
            repeat = await run_task(agent, task, judge_fn)
            if repeat.passed != score.passed:
                score = score.model_copy(update={"flake": True})
                flakes += 1
        scores.append(score)

    n = len(scores)
    pass_rate = sum(1 for s in scores if s.passed) / n if n else 0.0
    mean_score = sum(s.score for s in scores) / n if n else 0.0
    flake_rate = flakes / n if n else 0.0
    return EvalReport(
        suite_id=suite.id,
        manifest_id=suite.manifest_id,
        split=suite.split,
        task_scores=scores,
        pass_rate=pass_rate,
        mean_score=mean_score,
        flake_rate=flake_rate,
    )


async def evaluate_pair(
    manifest: AgentManifest,
    registries: Registries,
    pair: SuitePair,
    *,
    agents: dict[str, AgentManifest] | None = None,
    judge_fn: JudgeFn | None = None,
    measure_flake: bool = True,
) -> DevHeldOutReport:
    """Compile ``manifest`` once and run both splits against it (Section 14.1:
    iterate on dev, report dev+held-out side by side).
    """
    if manifest.id != pair.manifest_id:
        raise AgentCoreError(
            f"manifest id '{manifest.id}' does not match suite pair's manifest_id "
            f"'{pair.manifest_id}'"
        )
    agent = compile_agent(manifest, registries, agents=agents)
    dev_report = await run_suite(agent, pair.dev, judge_fn=judge_fn, measure_flake=measure_flake)
    held_out_report = await run_suite(
        agent, pair.held_out, judge_fn=judge_fn, measure_flake=measure_flake
    )
    gap = dev_report.pass_rate - held_out_report.pass_rate
    return DevHeldOutReport(
        manifest_id=manifest.id,
        dev=dev_report,
        held_out=held_out_report,
        overfitting_gap=gap,
        overfitting_flag=gap > _OVERFIT_GAP_THRESHOLD,
    )


# --------------------------------------------------------------------------- #
# Regression gate (Epic H5)
# --------------------------------------------------------------------------- #
class RegressionResult(BaseModel):
    """Outcome of gating a fresh report against a stored baseline."""

    model_config = _STRICT

    blocked: bool
    held_out_pass_rate: float
    baseline_pass_rate: float
    delta: float  # held_out.pass_rate - baseline.pass_rate; negative = regression
    newly_failing_tasks: list[str]
    newly_passing_tasks: list[str]
    dev_only_gain_flagged: bool
    detail: str


def check_regression(
    current: DevHeldOutReport,
    baseline_held_out: EvalReport,
    *,
    baseline_dev: EvalReport | None = None,
    tolerance: float = 0.05,
) -> RegressionResult:
    """Compare ``current`` (a fresh dev+held-out report) against a stored
    held-out baseline (PRD Section 14.3 / Epic H5). Blocks promotion when the
    held-out pass rate drops by more than ``tolerance``; surfaces the exact
    task-level diff (which tasks flipped pass<->fail) rather than just a
    number. When ``baseline_dev`` is also given, flags "dev-only gains" —
    dev improved but held-out did not, the overfitting signal from Section 14.1.
    """
    delta = current.held_out.pass_rate - baseline_held_out.pass_rate
    blocked = delta < -tolerance

    baseline_by_id = {s.task_id: s for s in baseline_held_out.task_scores}
    current_by_id = {s.task_id: s for s in current.held_out.task_scores}
    newly_failing = sorted(
        tid
        for tid, base in baseline_by_id.items()
        if base.passed and tid in current_by_id and not current_by_id[tid].passed
    )
    newly_passing = sorted(
        tid
        for tid, base in baseline_by_id.items()
        if not base.passed and tid in current_by_id and current_by_id[tid].passed
    )

    dev_only_gain_flagged = False
    if baseline_dev is not None:
        dev_delta = current.dev.pass_rate - baseline_dev.pass_rate
        dev_only_gain_flagged = dev_delta > tolerance and delta <= 0

    detail = (
        f"held-out pass_rate {current.held_out.pass_rate:.2f} vs baseline "
        f"{baseline_held_out.pass_rate:.2f} (delta={delta:+.2f}, tolerance={tolerance:.2f}); "
        f"newly failing: {newly_failing or 'none'}; newly passing: {newly_passing or 'none'}"
    )
    return RegressionResult(
        blocked=blocked,
        held_out_pass_rate=current.held_out.pass_rate,
        baseline_pass_rate=baseline_held_out.pass_rate,
        delta=delta,
        newly_failing_tasks=newly_failing,
        newly_passing_tasks=newly_passing,
        dev_only_gain_flagged=dev_only_gain_flagged,
        detail=detail,
    )
