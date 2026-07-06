"""AgentForge backend API (Phase 0 slice).

Exposes the Unified Agent Core over HTTP: a health check, the registered tool
list, and a manifest-validation endpoint that exercises the loader + resolver
end to end.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from agent_core import (
    __version__ as core_version,
    DockerCodeExecutor,
    InMemoryRunStore,
    MemoryItem,
    RunContext,
    RunRecord,
    Scope,
    build_default_registries,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
    token_cost,
    usage_totals,
)
from agent_core.errors import AgentCoreError

app = FastAPI(title="AgentForge API", version=core_version)

# Built once at startup; later phases will make these per-user / DB-backed.
registries = build_default_registries()
run_store = InMemoryRunStore()


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
        status = "error"
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
                yield _error_event(str(exc))
                return
            except Exception:
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
                        status = "timeout"
                    yield f"data: {event.model_dump_json()}\n\n"
            except AgentCoreError as exc:
                yield _error_event(str(exc))
                return
            except Exception:
                # Never leak internals/secrets/stack traces into the stream.
                yield _error_event("internal error during run")
                return

            cost = await persist()
            yield f"data: {json.dumps({'type': 'done', 'run_id': run_id, 'cost_usd': cost})}\n\n"
        finally:
            # Persist on every exit path, including client disconnect
            # (GeneratorExit) — awaiting is allowed here, only yielding is not.
            await persist()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
