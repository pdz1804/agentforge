"""AgentForge backend API (Phase 0 slice).

Exposes the Unified Agent Core over HTTP: a health check, the registered tool
list, and a manifest-validation endpoint that exercises the loader + resolver
end to end.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from agent_core import (
    __version__ as core_version,
    DockerCodeExecutor,
    MemoryItem,
    RunContext,
    RunRecord,
    Scope,
    build_default_registries,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
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


app = FastAPI(title="AgentForge API", version=core_version, lifespan=_lifespan)

# Built once at startup; later phases will make registries per-user / DB-backed.
registries = build_default_registries()
# Phase 8: opt-in durable run store. Defaults to InMemoryRunStore unless
# DATABASE_URL (or AGENTFORGE_RUN_STORE=postgres) is set and Postgres answers
# at startup — a misconfigured/unreachable DB falls back rather than crashing.
run_store = select_run_store()

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


class RunRequest(BaseModel):
    manifest: dict
    input: str
    eval_mode: bool = False
    thread_id: str = "default"
    agents: list[dict] = []  # sub-agent manifests the supervisor may delegate to


@app.post("/api/runs")
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
            await run_store.save(
                RunRecord(
                    id=run_id,
                    manifest_id=manifest_id,
                    model=model_name,
                    input=req.input,
                    status=status,
                    answer=answer,
                    trace=events,
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
                status = "error"
                yield _error_event("failed to prepare agent")
                return

            try:
                async for event in agent.astream(
                    req.input, eval_mode=req.eval_mode, thread_id=req.thread_id
                ):
                    events.append(event)
                    if event.type == "answer":
                        answer, status = event.detail, "completed"
                    elif event.type == "limit":
                        # Wall-clock overrun is a timeout; a step-budget stop is
                        # "incomplete" (stopped before answering) — neither is an error.
                        status = "timeout" if "wall_clock" in (event.detail or "") else "incomplete"
                    yield f"data: {event.model_dump_json()}\n\n"
            except AgentCoreError as exc:
                status = "error"
                yield _error_event(str(exc))
                return
            except Exception:
                # Never leak internals/secrets/stack traces into the stream.
                status = "error"
                yield _error_event("internal error during run")
                return

            cost = await persist()
            yield f"data: {json.dumps({'type': 'done', 'run_id': run_id, 'cost_usd': cost})}\n\n"
        finally:
            # Persist on every exit path, including client disconnect
            # (GeneratorExit) — awaiting is allowed here, only yielding is not.
            await persist()

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


# NOTE: the run history endpoints are unauthenticated and return raw inputs +
# full traces (which may contain tool outputs / memory) across all callers. Do
# not expose publicly until auth + per-user scoping land (Phase 11).
@app.get("/api/runs")
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


@app.get("/api/runs/{run_id}")
async def runs_get(run_id: str) -> dict:
    record = await run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.model_dump()


@app.get("/api/runs/{run_id}/export")
async def runs_export(run_id: str) -> dict:
    record = await run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.model_dump()  # full trace, JSON


def _error_event(detail: str) -> str:
    import json

    return f'data: {{"type": "error", "detail": {json.dumps(detail)}}}\n\n'


class SandboxRequest(BaseModel):
    code: str
    timeout_s: int = Field(default=15, ge=1, le=60)


@app.post("/api/sandbox/exec")
async def sandbox_exec(req: SandboxRequest) -> dict:
    """Run Python in the Docker sandbox and return the ExecResult.

    Network is always denied on this endpoint (no caller-controlled egress).
    Requires the docker CLI where the API runs; inside a container this needs the
    docker socket mounted (deferred deployment concern). NOTE: no auth/rate-limit
    yet (Phase 11) — do not expose publicly until then.
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


# NOTE: the memory endpoints are unauthenticated and honor caller-supplied
# scope/namespace — a caller can read/delete any bucket. Do not expose publicly
# until auth + per-user scoping land (Phase 11).
@app.get("/api/memory")
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


@app.post("/api/memory")
async def memory_add(req: MemoryAddRequest) -> dict:
    prov = _memory_provider(req.provider)
    await prov.add(_scope(req.scope), req.namespace, [MemoryItem(text=req.text)])
    return {"ok": True}


@app.delete("/api/memory")
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


@app.post("/api/index")
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


@app.post("/api/eval")
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

    body: dict = {"report": report.model_dump()}
    if req.baseline_held_out is not None:
        baseline_held_out = EvalReport.model_validate(req.baseline_held_out)
        baseline_dev = (
            EvalReport.model_validate(req.baseline_dev) if req.baseline_dev is not None else None
        )
        regression = check_regression(
            report,
            baseline_held_out,
            baseline_dev=baseline_dev,
            tolerance=req.regression_tolerance,
        )
        body["regression"] = regression.model_dump()
    return body
