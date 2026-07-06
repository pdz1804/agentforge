"""AgentForge backend API (Phase 0 slice).

Exposes the Unified Agent Core over HTTP: a health check, the registered tool
list, and a manifest-validation endpoint that exercises the loader + resolver
end to end.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_core import (
    __version__ as core_version,
    build_default_registries,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
)
from agent_core.errors import AgentCoreError

app = FastAPI(title="AgentForge API", version=core_version)

# Built once at startup; later phases will make this per-user / DB-backed.
registries = build_default_registries()


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


@app.post("/api/runs")
async def run_agent(req: RunRequest) -> StreamingResponse:
    """Run an agent, streaming trace events as Server-Sent Events.

    Validation errors are streamed as a single ``error`` event rather than an
    HTTP error, so a client on the SSE channel always gets a structured reply.
    """

    async def event_stream():
        try:
            manifest = load_manifest_dict(req.manifest)
            resolve_manifest(manifest, registries)
            agent = compile_agent(manifest, registries)
        except AgentCoreError as exc:
            yield _error_event(str(exc))
            return
        try:
            async for event in agent.astream(
                req.input, eval_mode=req.eval_mode, thread_id=req.thread_id
            ):
                yield f"data: {event.model_dump_json()}\n\n"
        except AgentCoreError as exc:
            yield _error_event(str(exc))
            return
        except Exception:
            # Never leak internals/secrets/stack traces into the stream.
            yield _error_event("internal error during run")
            return
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _error_event(detail: str) -> str:
    import json

    return f'data: {{"type": "error", "detail": {json.dumps(detail)}}}\n\n'
