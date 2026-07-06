# AgentForge

Multi-Agent Workbench & Code Sandbox. See [`PRD.md`](./PRD.md) and
[`IMPLEMENTATION-PLAN.md`](./IMPLEMENTATION-PLAN.md).

## Status

**Phase 0 (backend slice) + Phase 1 + Phase 2** implemented:

- `packages/agent-core` — declarative Agent Manifest schema, pluggable registries
  (tools / prompts / models / memory / MCP), core interfaces (`BaseTool`,
  `ModelProvider`, `MemoryProvider`, `CodeExecutor`, `MCPConnector`), a manifest
  loader + reference resolver, built-in Echo tool / model providers, and the
  **LangGraph runtime** (`compile_agent` → agent↔tools loop, `TraceEvent` bus,
  `arun` / `astream`, `max_steps` + `wall_clock_s` limits, eval-mode temp=0).
  Model providers are registry-selected per manifest (`model.provider`):
  **`anthropic`** and **`openai`** (both with tool-use), plus an offline
  **`echo`**. **`web_search`** tool via Tavily.
- `apps/api` — FastAPI service: `/health`, `/api/tools`, `/api/agents/validate`,
  `POST /api/runs` (SSE streaming answer + trace); Dockerfile + compose `api` service.
- `infra/` — Postgres + the API via Docker Compose.

Deferred to later phases: Next.js web UI; `EmbeddingSearchTool`+pgvector + MCP
connector (Phase 3b); sandbox (Phase 4); memory + durable checkpointer
(Phase 5); eval harness (Phase 9).

### Choosing a provider

Set the manifest's `model.provider` to `anthropic`, `openai`, or `echo`. Provide
the matching key in `.env` (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) and
`TAVILY_API_KEY` for `web_search`. Add a new provider by implementing
`ModelProvider` and registering it — no core edits.

## Layout

```
packages/agent-core/   # shared core (also consumed by FloraLens)
apps/api/              # FastAPI backend
infra/                 # docker-compose (Postgres)
suites/                # eval task suites (Phase 9)
```

## Quickstart

```bash
# 1. Create a virtual env
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate

# 2. Install the core (editable) + API deps
pip install -e packages/agent-core
pip install -r apps/api/requirements.txt

# 3. Run the tests
pytest packages/agent-core
pytest apps/api

# 4. Run the API
uvicorn app.main:app --reload --app-dir apps/api
# -> http://127.0.0.1:8000/health

# 5. (optional) Start Postgres
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d
```

## Extending the core (no core edits)

```python
from agent_core import BaseTool, ToolResult, build_default_registries

class WeatherTool(BaseTool):
    name = "weather"
    description = "Get the weather for a city."
    args_schema = WeatherArgs      # a pydantic model

    async def run(self, **kwargs):
        ...
        return ToolResult(output=...)

registries = build_default_registries()
registries.tools.register("weather", WeatherTool())
# Any manifest may now list `weather` under its tools.
```
