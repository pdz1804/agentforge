"""AgentForge backend API (Phase 0 slice).

Exposes the Unified Agent Core over HTTP: a health check, the registered tool
list, and a manifest-validation endpoint that exercises the loader + resolver
end to end.

Additive (PRD Phase 11 — opt-in hardening; see auth.py, rate_limit.py,
redaction.py): sensitive endpoints (run execution + history, eval, sandbox,
memory, index) sit behind `require_api_key`, a no-op unless
`AGENTFORGE_API_KEY` is set, so the local demo and existing tests are
unaffected by default. `/api/runs`, `/api/eval`, and `/api/sandbox/exec` are
additionally per-IP rate limited, and secrets are redacted from the run
trace/error stream and from all log output.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from app.auth import require_api_key
from app.env_loader import load_env_files
from app.rate_limit import eval_rate_limit, runs_rate_limit, sandbox_rate_limit
from app.redaction import RedactingLogFilter, redact_secrets

from agent_core import (
    __version__ as core_version,
    DockerCodeExecutor,
    MemoryItem,
    RunContext,
    RunRecord,
    Scope,
    StoredBaseline,
    build_default_registries,
    compile_agent,
    diff_manifest_versions,
    load_manifest_dict,
    resolve_manifest,
    select_eval_report_store,
    select_manifest_store,
    select_run_store,
    token_cost,
    usage_totals,
)
from agent_core.errors import AgentCoreError
from agent_core.eval import (
    DevHeldOutReport,
    EvalReport,
    JudgeFn,
    SuitePair,
    check_disjoint,
    check_regression,
    collect_spot_check_samples,
    discover_suite_pairs,
    evaluate_pair,
    load_suite_dict,
    make_model_judge_fn,
)

@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    # Shutdown: InMemoryRunStore (the default) has no `close`; only
    # PostgresRunStore's connection pool needs releasing, so this is a no-op
    # unless a caller opted into Phase 8's durable store.
    close = getattr(run_store, "close", None)
    if close is not None:
        await close()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Scrubs secrets (API keys, bearer tokens, ...) from every log record
# process-wide, in case one ends up in an exception message (PRD Phase 11).
# The filter must sit on the HANDLERS, not the root logger: a logger's own
# filters only run for records logged directly on it, so records propagated
# up from named child loggers (logging.getLogger(__name__)) bypass a
# root-logger filter but still pass through the root's handlers.
_redacting_filter = RedactingLogFilter()
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_redacting_filter)

app = FastAPI(title="AgentForge API", version=core_version, lifespan=_lifespan)

# Local-dev convenience: load repo-root .env (API keys, DATABASE_URL) so a plain
# `uvicorn app.main:app` picks them up the way docker-compose / a sourced shell
# would — otherwise the server starts keyless and only fails later on the first
# OpenAI-backed run. Runs BEFORE select_run_store() (which reads DATABASE_URL)
# and provider construction. Skipped under pytest so tests never inherit a
# developer's .env; already-set env vars always win (setdefault semantics).
if "pytest" not in sys.modules:
    load_env_files(Path(__file__).resolve().parents[3] / ".env")

# Built once at startup; later phases will make registries per-user / DB-backed.
registries = build_default_registries()
# Phase 8: opt-in durable run store. Defaults to InMemoryRunStore unless
# DATABASE_URL (or AGENTFORGE_RUN_STORE=postgres) is set and Postgres answers
# at startup — a misconfigured/unreachable DB falls back rather than crashing.
run_store = select_run_store()
# G4/G5: manifest version history + eval report/baseline persistence. Both
# default to their in-memory backend (same opt-in seam as the run store), so
# the local demo and existing tests are unaffected.
manifest_store = select_manifest_store()
eval_report_store = select_eval_report_store()

# Repo-root suites/ directory: apps/api/app/main.py -> app -> api -> apps -> root.
# Overridable via env for deployments where the repo layout differs.
_DEFAULT_SUITES_DIR = Path(__file__).resolve().parents[3] / "suites"
SUITES_DIR = Path(os.environ.get("AGENTFORGE_SUITES_DIR") or _DEFAULT_SUITES_DIR)

# Fixed judge model + temperature=0 (PRD Section 14.2). Constructing this wrapper
# makes no network call; only an actual llm_judge task invocation does, and only
# if OPENAI_API_KEY is configured. Tests never exercise this path — they inject
# a fake JudgeFn directly against agent_core.eval's scoring functions.
eval_judge_fn: JudgeFn = make_model_judge_fn(registries.models.get("openai"), model="gpt-4o-mini")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "core_version": core_version,
        "tools": registries.tools.list(),
        "models": registries.models.list(),
    }


@app.get("/api/tools")
def list_tools() -> dict:
    return {"tools": registries.tools.list()}


class ValidateRequest(BaseModel):
    manifest: dict


class ValidateResponse(BaseModel):
    ok: bool
    id: str | None = None
    error: str | None = None


@app.post("/api/agents/validate", response_model=ValidateResponse)
def validate_agent(req: ValidateRequest) -> ValidateResponse:
    """Validate a manifest's schema and resolve its references."""
    try:
        manifest = load_manifest_dict(req.manifest)
        resolve_manifest(manifest, registries)
    except AgentCoreError as exc:
        return ValidateResponse(ok=False, error=str(exc))
    return ValidateResponse(ok=True, id=manifest.id)


# --------------------------------------------------------------------------- #
# Manifest persistence + version history (Gap G4). These routes mutate/return
# stored agent definitions, so they sit behind require_api_key like the other
# stateful endpoints (no-op unless AGENTFORGE_API_KEY is set). The existing
# stateless POST /api/agents/validate above is intentionally left public and
# unchanged.
# --------------------------------------------------------------------------- #
class ManifestRequest(BaseModel):
    manifest: dict


def _validate_manifest_or_400(raw: dict):
    """Reuse the loader/resolver validation path; raise 400 on a bad manifest.

    Same checks as /api/agents/validate — a manifest is only stored once it
    parses and every reference resolves.
    """
    try:
        manifest = load_manifest_dict(raw)
        resolve_manifest(manifest, registries)
    except AgentCoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return manifest


@app.post("/api/agents", dependencies=[Depends(require_api_key)])
async def create_agent(req: ManifestRequest) -> dict:
    """Validate a manifest and store it as a new version (v1 for a new id)."""
    manifest = _validate_manifest_or_400(req.manifest)
    created_at = datetime.now(timezone.utc).isoformat()
    record = await manifest_store.save(manifest.id, req.manifest, created_at=created_at)
    return record.model_dump()


@app.get("/api/agents", dependencies=[Depends(require_api_key)])
async def list_agents() -> dict:
    """List stored manifest ids with their current (latest) version number."""
    ids = await manifest_store.list_ids()
    agents = []
    for manifest_id in ids:
        latest = await manifest_store.get(manifest_id)
        if latest is not None:
            agents.append({"id": manifest_id, "latest_version": latest.version})
    return {"agents": agents}


@app.get("/api/agents/{manifest_id}", dependencies=[Depends(require_api_key)])
async def get_agent(manifest_id: str, version: int | None = None) -> dict:
    """Fetch the latest stored version, or a specific one via ``?version=N``."""
    record = await manifest_store.get(manifest_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail="agent (or version) not found")
    return record.model_dump()


@app.put("/api/agents/{manifest_id}", dependencies=[Depends(require_api_key)])
async def update_agent(manifest_id: str, req: ManifestRequest) -> dict:
    """Validate and store a new version of ``manifest_id``.

    The manifest body's own ``id`` must match the path id — storing a manifest
    under a mismatched id would silently fork history.
    """
    manifest = _validate_manifest_or_400(req.manifest)
    if manifest.id != manifest_id:
        raise HTTPException(
            status_code=400,
            detail=f"manifest id '{manifest.id}' does not match path id '{manifest_id}'",
        )
    created_at = datetime.now(timezone.utc).isoformat()
    record = await manifest_store.save(manifest_id, req.manifest, created_at=created_at)
    return record.model_dump()


@app.get("/api/agents/{manifest_id}/versions", dependencies=[Depends(require_api_key)])
async def list_agent_versions(manifest_id: str) -> dict:
    """Return the full version history for ``manifest_id`` (oldest first)."""
    versions = await manifest_store.list_versions(manifest_id)
    if not versions:
        raise HTTPException(status_code=404, detail="agent not found")
    return {"manifest_id": manifest_id, "versions": [v.model_dump() for v in versions]}


@app.get("/api/agents/{manifest_id}/diff", dependencies=[Depends(require_api_key)])
async def diff_agent_versions(
    manifest_id: str,
    from_: int = Query(..., alias="from"),  # 'from' is a Python keyword; alias the query param
    to: int = Query(...),
) -> dict:
    """Field + unified-text diff between two stored versions (``?from=&to=``)."""
    older = await manifest_store.get(manifest_id, from_)
    newer = await manifest_store.get(manifest_id, to)
    if older is None or newer is None:
        raise HTTPException(status_code=404, detail="agent (or version) not found")
    return diff_manifest_versions(older, newer)


class RunRequest(BaseModel):
    manifest: dict
    input: str
    eval_mode: bool = False
    # None => isolate this run under its own unique thread (the run id). A
    # shared literal default would make LangGraph key every checkpointer-backed
    # run to the SAME thread, so two clients that both omit thread_id would
    # resume each other's conversation. Pass an explicit id ONLY to continue a
    # prior thread on purpose.
    thread_id: str | None = None
    agents: list[dict] = []  # sub-agent manifests the supervisor may delegate to


@app.post("/api/runs", dependencies=[Depends(require_api_key), Depends(runs_rate_limit)])
async def run_agent(req: RunRequest) -> StreamingResponse:
    """Run an agent, streaming trace events as Server-Sent Events.

    Validation errors are streamed as a single ``error`` event rather than an
    HTTP error, so a client on the SSE channel always gets a structured reply.
    """

    run_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    manifest_id = str(req.manifest.get("id", "unknown"))
    model_name = str((req.manifest.get("model") or {}).get("name", "unknown"))

    async def event_stream():
        events: list = []
        answer: str | None = None
        # Bound before the compile try so the finally can aclose it even if
        # compilation failed. Stays None on the compile-error path.
        agent = None
        # "incomplete" until a terminal event decides otherwise; "error" is set
        # only on a real failure (below), never as the default for a clean run.
        status = "incomplete"
        persisted = False

        async def persist() -> float:
            # Idempotent: exactly one save per request even across the finally.
            # NOTE: multi-agent runs under-count cost — a sub-agent's tokens live
            # in its own (non-inlined) trace, so cost_usd is a lower bound.
            nonlocal persisted
            usage = usage_totals(events)
            cost = token_cost(usage, model_name)
            if persisted:
                return cost
            persisted = True
            # Redact before persisting, not only on the wire: the durable store
            # is served verbatim by GET /api/runs/{id} and /export, so a secret
            # a tool echoed into its output must be scrubbed here too — otherwise
            # the live stream shows [REDACTED] while the system of record leaks
            # the key. Round-trip each event through its JSON form so redaction
            # reaches nested tool_calls/args, not just top-level detail strings.
            redacted_events = [
                type(e).model_validate_json(redact_secrets(e.model_dump_json()))
                for e in events
            ]
            await run_store.save(
                RunRecord(
                    id=run_id,
                    manifest_id=manifest_id,
                    model=model_name,
                    input=req.input,
                    status=status,
                    answer=redact_secrets(answer) if answer else answer,
                    trace=redacted_events,
                    usage=usage,
                    cost_usd=cost,
                    created_at=created_at,
                )
            )
            return cost

        yield f"data: {json.dumps({'type': 'run_started', 'run_id': run_id})}\n\n"
        try:
            try:
                manifest = load_manifest_dict(req.manifest)
                sub_agents = {}
                for raw in req.agents:
                    sub = load_manifest_dict(raw)
                    sub_agents[sub.id] = sub
                known = set(sub_agents)
                resolve_manifest(manifest, registries, known_agents=known)
                for sub in sub_agents.values():
                    resolve_manifest(sub, registries, known_agents=known)
                agent = compile_agent(manifest, registries, agents=sub_agents)
            except AgentCoreError as exc:
                status = "error"
                yield _error_event(str(exc))
                return
            except Exception:
                logger.exception("failed to prepare agent for run %s", run_id)
                status = "error"
                yield _error_event("failed to prepare agent")
                return

            try:
                async for event in agent.astream(
                    req.input, eval_mode=req.eval_mode, thread_id=req.thread_id or run_id
                ):
                    events.append(event)
                    if event.type == "answer":
                        answer, status = event.detail, "completed"
                    elif event.type == "limit":
                        # Wall-clock overrun is a timeout; a step-budget stop is
                        # "incomplete" (stopped before answering) — neither is an error.
                        status = "timeout" if "wall_clock" in (event.detail or "") else "incomplete"
                    # Tool outputs may echo back secrets (e.g. a misconfigured
                    # tool leaking an env var); scrub before it hits the wire.
                    yield f"data: {redact_secrets(event.model_dump_json())}\n\n"
            except AgentCoreError as exc:
                status = "error"
                yield _error_event(str(exc))
                return
            except Exception:
                # Never leak internals/secrets/stack traces into the stream.
                logger.exception("run %s failed", run_id)
                status = "error"
                yield _error_event("internal error during run")
                return

            cost = await persist()
            yield f"data: {json.dumps({'type': 'done', 'run_id': run_id, 'cost_usd': cost})}\n\n"
        finally:
            # Persist on every exit path, including client disconnect
            # (GeneratorExit) — awaiting is allowed here, only yielding is not.
            await persist()
            # Release the per-run checkpointer's resources (sqlite connection +
            # its background thread). A fresh agent is compiled per request, so
            # without this every run with AGENTFORGE_CHECKPOINT_DB set would leak
            # a connection/thread. No-op in the default no-checkpointer setup.
            if agent is not None:
                await agent.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Defense-in-depth against proxy buffering of the live stream.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# The run history endpoints return raw inputs + full traces (which may
# contain tool outputs / memory) across all callers, so they sit behind
# require_api_key like the other sensitive endpoints (no-op unless
# AGENTFORGE_API_KEY is set).
@app.get("/api/runs", dependencies=[Depends(require_api_key)])
async def runs_list(limit: int = 50) -> dict:
    records = await run_store.list(limit)
    return {
        "runs": [
            {
                "id": r.id,
                "manifest_id": r.manifest_id,
                "model": r.model,
                "status": r.status,
                "cost_usd": r.cost_usd,
                "created_at": r.created_at,
                "answer": r.answer,
            }
            for r in records
        ]
    }


@app.get("/api/runs/{run_id}", dependencies=[Depends(require_api_key)])
async def runs_get(run_id: str) -> dict:
    record = await run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.model_dump()


@app.get("/api/runs/{run_id}/export", dependencies=[Depends(require_api_key)])
async def runs_export(run_id: str) -> dict:
    record = await run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.model_dump()  # full trace, JSON


def _error_event(detail: str) -> str:
    import json

    return f'data: {{"type": "error", "detail": {json.dumps(redact_secrets(detail))}}}\n\n'


class SandboxRequest(BaseModel):
    code: str
    timeout_s: int = Field(default=15, ge=1, le=60)


@app.post(
    "/api/sandbox/exec",
    dependencies=[Depends(require_api_key), Depends(sandbox_rate_limit)],
)
async def sandbox_exec(req: SandboxRequest) -> dict:
    """Run Python in the Docker sandbox and return the ExecResult.

    Network is always denied on this endpoint (no caller-controlled egress).
    Requires the docker CLI where the API runs; inside a container this needs the
    docker socket mounted (deferred deployment concern).
    """
    executor = DockerCodeExecutor()
    try:
        result = await executor.run(
            req.code, RunContext(wall_clock_s=req.timeout_s, allow_network=False)
        )
    except Exception:
        return {"stdout": "", "stderr": "sandbox unavailable", "exit_code": 1, "timed_out": False}
    return result.model_dump()


def _memory_provider(provider: str):
    try:
        return registries.memory.get(provider)
    except AgentCoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _scope(value: str) -> Scope:
    try:
        return Scope(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid scope '{value}'") from None


class MemoryAddRequest(BaseModel):
    text: str
    provider: str = "in_memory"
    scope: str = "user"
    namespace: str = "default"


# The memory endpoints honor caller-supplied scope/namespace — a caller can
# read/delete any bucket — so they sit behind require_api_key like the other
# sensitive endpoints (no-op unless AGENTFORGE_API_KEY is set).
@app.get("/api/memory", dependencies=[Depends(require_api_key)])
async def memory_list(
    provider: str = "in_memory",
    scope: str = "user",
    namespace: str = "default",
    query: str | None = None,
) -> dict:
    prov = _memory_provider(provider)
    sc = _scope(scope)
    items = await (prov.search(sc, namespace, query, 20) if query else prov.all(sc, namespace))
    return {"items": [i.model_dump() for i in items]}


@app.post("/api/memory", dependencies=[Depends(require_api_key)])
async def memory_add(req: MemoryAddRequest) -> dict:
    prov = _memory_provider(req.provider)
    await prov.add(_scope(req.scope), req.namespace, [MemoryItem(text=req.text)])
    return {"ok": True}


@app.delete("/api/memory", dependencies=[Depends(require_api_key)])
async def memory_delete(
    id: str,
    provider: str = "in_memory",
    scope: str = "user",
    namespace: str = "default",
) -> dict:
    prov = _memory_provider(provider)
    await prov.delete(_scope(scope), namespace, [id])
    return {"ok": True}


class IndexRequest(BaseModel):
    doc_id: str
    text: str


@app.post("/api/index", dependencies=[Depends(require_api_key)])
async def index_document(req: IndexRequest) -> dict:
    """Embed + index a document into the default embedding_search corpus.

    Needs OPENAI_API_KEY (embeddings); returns a structured error otherwise.
    """
    tool = registries.tools.get("embedding_search")
    try:
        await tool.index(req.doc_id, req.text)
    except AgentCoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "doc_id": req.doc_id}


# --------------------------------------------------------------------------- #
# Agent evaluation harness (Phase 9, PRD Section 14) — dev/held-out eval runs.
# --------------------------------------------------------------------------- #
@app.get("/api/suites")
def list_suites() -> dict:
    """List available dev/held-out suite pairs discovered under ``suites/``."""
    try:
        pairs = discover_suite_pairs(SUITES_DIR)
    except AgentCoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "suites": [
            {
                "suite_id": pair.group_id,
                "manifest_id": pair.manifest_id,
                "dev_task_count": len(pair.dev.tasks),
                "held_out_task_count": len(pair.held_out.tasks),
            }
            for pair in pairs.values()
        ]
    }


class EvalRequest(BaseModel):
    manifest: dict
    agents: list[dict] = []  # sub-agent manifests, same shape as RunRequest
    suite_id: str | None = None  # resolve dev+held_out pair from suites/
    dev_suite: dict | None = None  # or: provide both splits inline
    held_out_suite: dict | None = None
    measure_flake: bool = True  # re-run each task once to detect nondeterminism
    # Optional regression gate: a previously stored held-out (+ dev) EvalReport
    # to compare this run against (PRD Section 14.3 / Epic H5).
    baseline_held_out: dict | None = None
    baseline_dev: dict | None = None
    # Alternatively, gate against the baseline stored server-side for this
    # manifest (Gap G5) instead of shipping it inline. The inline fields above
    # take precedence when both are supplied.
    use_stored_baseline: bool = False
    regression_tolerance: float = 0.05

    @model_validator(mode="after")
    def _check_suite_source(self) -> "EvalRequest":
        has_id = self.suite_id is not None
        has_inline = self.dev_suite is not None and self.held_out_suite is not None
        if has_id == has_inline:  # both or neither supplied
            raise ValueError(
                "provide exactly one of 'suite_id' or both 'dev_suite' + 'held_out_suite'"
            )
        return self


@app.post(
    "/api/eval",
    dependencies=[Depends(require_api_key), Depends(eval_rate_limit)],
)
async def run_eval(req: EvalRequest) -> dict:
    """Run a manifest's dev + held-out suites and return the side-by-side report.

    Reuses the same compile/resolve path as ``/api/runs``; each task runs in
    deterministic eval mode (temp=0, memory-isolated). If ``baseline_held_out``
    is supplied, the response also includes a regression-gate verdict.
    """
    try:
        manifest = load_manifest_dict(req.manifest)
        sub_agents = {}
        for raw in req.agents:
            sub = load_manifest_dict(raw)
            sub_agents[sub.id] = sub
        known = set(sub_agents)
        resolve_manifest(manifest, registries, known_agents=known)
        for sub in sub_agents.values():
            resolve_manifest(sub, registries, known_agents=known)

        if req.suite_id is not None:
            pairs = discover_suite_pairs(SUITES_DIR)
            if req.suite_id not in pairs:
                raise HTTPException(
                    status_code=404,
                    detail=f"unknown suite_id '{req.suite_id}'. available: {sorted(pairs)}",
                )
            pair = pairs[req.suite_id]
        else:
            dev = load_suite_dict(req.dev_suite)
            held_out = load_suite_dict(req.held_out_suite)
            check_disjoint(dev, held_out)
            pair = SuitePair(
                group_id=dev.id, manifest_id=dev.manifest_id, dev=dev, held_out=held_out
            )

        report: DevHeldOutReport = await evaluate_pair(
            manifest,
            registries,
            pair,
            agents=sub_agents,
            judge_fn=eval_judge_fn,
            measure_flake=req.measure_flake,
        )
    except AgentCoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Persist every eval run so its report can be fetched later and promoted to
    # a baseline (Gap G5). The generated id is returned to the caller.
    report_id = uuid.uuid4().hex
    await eval_report_store.save_report(
        report_id, report, created_at=datetime.now(timezone.utc).isoformat()
    )
    # Capture llm_judge-scored tasks for periodic human audit (PRD 14.2). Stored
    # separately from the report, so a run with no judge tasks records an empty
    # list and its report serialization is unchanged.
    spot_check_samples = collect_spot_check_samples(
        pair.dev, report.dev
    ) + collect_spot_check_samples(pair.held_out, report.held_out)
    await eval_report_store.save_spot_check(report_id, spot_check_samples)
    body: dict = {"report_id": report_id, "report": report.model_dump()}

    # Resolve the regression baseline from one of two sources: an inline
    # client-supplied baseline (original contract), or the baseline stored
    # server-side for this manifest (Gap G5). Inline wins if both are present.
    baseline_held_out: EvalReport | None = None
    baseline_dev: EvalReport | None = None
    if req.baseline_held_out is not None:
        # A malformed client-supplied baseline is a 422, not a 500 — validate
        # inside the handler (this runs after the try/except above closes).
        try:
            baseline_held_out = EvalReport.model_validate(req.baseline_held_out)
            baseline_dev = (
                EvalReport.model_validate(req.baseline_dev)
                if req.baseline_dev is not None
                else None
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"invalid baseline report: {exc}") from exc
    elif req.use_stored_baseline:
        stored = await eval_report_store.get_baseline(manifest.id)
        if stored is None:
            raise HTTPException(
                status_code=404,
                detail=f"no stored baseline for manifest '{manifest.id}'; promote a report first",
            )
        baseline_held_out = stored.held_out
        baseline_dev = stored.dev

    if baseline_held_out is not None:
        regression = check_regression(
            report,
            baseline_held_out,
            baseline_dev=baseline_dev,
            tolerance=req.regression_tolerance,
        )
        body["regression"] = regression.model_dump()
    return body


@app.get("/api/eval/{report_id}", dependencies=[Depends(require_api_key)])
async def get_eval_report(report_id: str) -> dict:
    """Fetch a previously stored eval report by its id (Gap G5)."""
    stored = await eval_report_store.get_report(report_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="eval report not found")
    return stored.model_dump()


@app.get("/api/eval/{report_id}/spot-check", dependencies=[Depends(require_api_key)])
async def get_eval_spot_check(report_id: str) -> dict:
    """List a stored report's llm_judge samples queued for human audit (PRD 14.2).

    Read-only: surfaces each judged task's input, agent answer, and the judge's
    raw score/verdict so a human can periodically re-check the judge. Reports
    with no llm_judge tasks return an empty ``samples`` list.
    """
    stored = await eval_report_store.get_report(report_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="eval report not found")
    samples = await eval_report_store.get_spot_check(report_id)
    return {
        "report_id": report_id,
        "manifest_id": stored.manifest_id,
        "samples": [s.model_dump() for s in samples],
    }


@app.post("/api/eval/{report_id}/promote", dependencies=[Depends(require_api_key)])
async def promote_eval_baseline(report_id: str) -> dict:
    """Promote a stored report's held-out split to its manifest's baseline.

    After this, an eval run for the same manifest can gate against the stored
    baseline via ``use_stored_baseline`` instead of shipping one inline.
    """
    stored = await eval_report_store.get_report(report_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="eval report not found")
    baseline = StoredBaseline(
        manifest_id=stored.manifest_id,
        held_out=stored.report.held_out,
        dev=stored.report.dev,
        source_report_id=report_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await eval_report_store.set_baseline(baseline)
    return {
        "manifest_id": stored.manifest_id,
        "source_report_id": report_id,
        "baseline_pass_rate": baseline.held_out.pass_rate,
    }
