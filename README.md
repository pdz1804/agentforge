# AgentForge

Multi-Agent Workbench & Code Sandbox. See [`PRD.md`](./PRD.md) and
[`IMPLEMENTATION-PLAN.md`](./IMPLEMENTATION-PLAN.md).

## Status

**Phases 0–10 and 12 implemented. Phase 11 (auth/hardening) partial.**

- `packages/agent-core` — declarative Agent Manifest schema, pluggable registries
  (tools / prompts / models / memory / MCP), core interfaces (`BaseTool`,
  `ModelProvider`, `MemoryProvider`, `CodeExecutor`, `MCPConnector`), a manifest
  loader + reference resolver, built-in Echo tool / model providers, and the
  **LangGraph runtime** (`compile_agent` → agent↔tools loop, `TraceEvent` bus,
  `arun` / `astream`, `max_steps` + `wall_clock_s` limits, eval-mode temp=0).
  Model providers: **`anthropic`** and **`openai`** (both tool-use), **`echo`** (offline).
  Tools: **`web_search`** (Tavily), **`code_executor`** (Docker sandbox, deny-by-default),
  **`embedding_search`** (semantic search + InMemoryVectorStore), **`http_fetch`**.
  Long-term **memory** (`InMemoryMemoryProvider` default, optional `mem0`). **MCP connector**.
  **Multi-agent supervisor** with `sub_agents` exposed as delegation tools. **Run persistence** 
  with full trace + token/cost accounting (`RunStore`). **Docker code sandbox** with 
  security matrix (8-row test, passed).
- `apps/api` — FastAPI on **port 8077** (configurable): `/health`, `/api/tools`, `/api/agents/validate`,
  `POST /api/runs` (SSE), `GET /api/runs` + `GET /api/runs/{id}[/export]`,
  `POST /api/sandbox/exec`, `GET/POST/DELETE /api/memory`, `POST /api/index`;
  Dockerfile + Docker Compose.
- `apps/web` — **Next.js 14 Agent Builder UI**: YAML manifest editor, validation, live SSE run panel,
  trace view with **3D execution graph** (Three.js node/edge animation, timeline scrubber, reduced-motion
  fallback), run history, **dark/light theme toggle**, **Builder/About tabs**, intro page.
  Proxies `/api` to FastAPI backend (no CORS). Playwright e2e tests included.
- `infra/` — Postgres + the API via Docker Compose.

Shipped since: Phase 9 (agent eval harness — `eval.py`, `POST /api/eval`, `eval-panel.tsx`:
dev/held-out split, programmatic/rubric/LLM-judge scoring, regression gate); Phase 10 (CI test
pyramid — `.github/workflows/ci.yml` + conformance/extension-conformance tests + sandbox-security
gate); Phase 8 durable `PostgresRunStore` + retention; Phase 12 (FloraLens naturalist assistant
runs on unmodified `agent_core`). Phase 11 is **partial**: opt-in shared-key auth
(`AGENTFORGE_API_KEY`), rate limiting, and secret redaction in traces/logs are in place, but there
is no per-user isolation yet (a single shared key). E2B sandbox backend still deferred (Docker executor ships).

### Choosing a provider

Set the manifest's `model.provider` to `anthropic`, `openai`, or `echo`. Provide
the matching key in `.env` (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) and
`TAVILY_API_KEY` for `web_search`. Add a new provider by implementing
`ModelProvider` and registering it — no core edits.

## Layout

```
packages/agent-core/   # shared core (also consumed by FloraLens)
apps/api/              # FastAPI backend
apps/web/              # Next.js Agent Builder UI (manifest editor, live run panel,
                       #   trace view, run history, 3D execution graph) + Playwright e2e
infra/                 # docker-compose (Postgres)
suites/                # eval task suites (Phase 9)
```

## Web UI (`apps/web`)

**Next.js 14 Agent Builder** with live dashboard and 3D execution visualization.

**Features:**
- **Manifest Editor**: YAML editor with template gallery; real-time validation; syntax highlighting.
- **Live Run Panel**: Stream agent execution over SSE; show tool calls, model responses, and errors in real-time.
- **3D Execution Graph** (Phase 7): Three.js visualization of agent nodes, tool nodes, and message flow. 
  Timeline scrubber replays the run step-by-step. Nodes pulse on activation; edges highlight tool calls.
  2D SVG + reduced-motion fallback (no WebGL required).
- **Run History**: List all runs (newest first) with status, model, timestamp, token usage. Click to view 
  full trace or export JSON.
- **Theme Toggle**: Dark/light mode with persistent preference.
- **Tabs**: Builder (editor + run) and About (docs/help).
- **API Proxy**: Single origin — proxies `/api` to the FastAPI backend via Next rewrites (no CORS).

```bash
# Assuming API is running on :8077 (or set API_PORT in .env)
cd apps/web
npm install
npm run dev              # Development server on http://localhost:3000
npm run build && npm start  # Production build
npx playwright test      # E2E tests (set SKIP_LIVE=1 to skip billed API calls)
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

# 4. Run the API (port 8077 by default; configurable via API_PORT env)
uvicorn app.main:app --reload --port 8077 --app-dir apps/api
# -> http://127.0.0.1:8077/health

# 5. Run the web UI (in a new terminal)
cd apps/web
npm install
npm run dev
# -> http://localhost:3000 (proxies API to :8077)

# 6. (optional) Start Postgres for persistence
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
