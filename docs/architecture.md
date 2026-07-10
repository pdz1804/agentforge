# AgentForge Architecture

AgentForge is a full-stack workbench for building, running, evaluating, and extending multi-agent AI systems. This document describes the system architecture, data models, and runtime flow.

---

## System Layers

AgentForge consists of three core layers:

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (Next.js + React + Three.js)                       │
│  Agent Builder | Run Panel (SSE) | 3D Graph | Eval Viewer    │
└─────────┬────────────────────────────────────────────────────┘
          │ HTTP/SSE (port 3000 → 8077)
┌─────────▼────────────────────────────────────────────────────┐
│  Backend (FastAPI on port 8077)                              │
│  /agents /runs /eval /tools /sandbox /memory /suites         │
└─────────┬────────────────────────────────────────────────────┘
          │ (imports)
┌─────────▼────────────────────────────────────────────────────┐
│  Unified Agent Core (packages/agent-core)                    │
│  Manifest | Registries | LangGraph Runtime | Eval | Tools    │
└─────────┬────────────────────────────────────────────────────┘
          │ (optional connections)
┌─────────▼────────────────────────────────────────────────────┐
│  Persistence & External Services                            │
│  Postgres (runs/traces/evals) | Docker Sandbox | MCP Servers │
└──────────────────────────────────────────────────────────────┘
```

### Layer 1: Frontend (`apps/web`)
- **Stack:** Next.js 14, React, TypeScript, Three.js
- **Responsibilities:**
  - YAML/JSON manifest editor with live validation
  - Live run panel: stream events from SSE, show tool calls and responses
  - 3D execution graph: animate nodes and edges, timeline scrubber replay
  - Run history: list, filter, export as JSON
  - Eval viewer: side-by-side dev/held-out reports
  - Dark/light theme toggle

### Layer 2: Backend (`apps/api`)
- **Stack:** FastAPI (Python), Pydantic
- **Responsibilities:**
  - REST + SSE endpoints (agents, runs, eval, sandbox, memory, observability)
  - Request validation and error handling
  - Manifest persistence (optional Postgres backend)
  - Eval report storage and promotion
  - Rate limiting, optional API key auth, secret redaction
  - Proxy to the Unified Agent Core

### Layer 3: Unified Agent Core (`packages/agent-core`)
- **Stack:** Python, LangGraph, Pydantic
- **Responsibilities:**
  - Manifest schema and loader
  - Pluggable registries (tools, models, memory, MCP, prompts)
  - LangGraph compilation: manifest → StateGraph → executable agent
  - Trace event bus
  - Eval harness (dev/held-out split, scoring modes, regression gate)
  - Built-in tools (web search, code executor, embedding search, HTTP fetch)
  - Memory providers (in-memory, mem0)
  - Sandbox interface (Docker backend)
  - MCP connector

The core is **reusable**: FloraLens installs it as an editable dependency and runs naturalist agents against the same code without modifications.

---

## Agent Manifest and Runtime

### Manifest Schema

An agent is fully defined by a declarative YAML or JSON manifest:

```yaml
id: coder_supervisor
version: 3
model:
  provider: anthropic              # ModelProvider registry key
  name: claude-sonnet-5            # Model name
  temperature: 0.2                 # 0 for eval, 0.2+ for generation
  max_tokens: 4096
prompt_ref: prompts/coder.md       # PromptRegistry key (YAML/markdown ref)
memory:
  provider: in_memory              # MemoryProvider: in_memory or mem0
  scope: user                       # user | agent | session
  namespace: agentforge
tools: [web_search, code_executor] # ToolRegistry keys (allowlist)
mcp_servers: [github_mcp]          # MCPRegistry keys
sub_agents: [planner, coder]       # Multi-agent delegation
guardrails: [no_secret_exfil]      # GuardrailRegistry keys
io_schema:
  input: CoderRequest              # Pydantic model (input validation)
  output: CoderResult              # Pydantic model (output validation)
limits:
  max_steps: 20                     # Max agent loop iterations
  max_tokens_total: 200000         # Total tokens across entire run
  wall_clock_s: 120                # Wall-clock timeout in seconds
eval_suite: suites/coder_v1        # Eval task suite for this manifest
```

**Key properties:**
- **Declarative:** No code needed to define an agent; configuration is data.
- **Validated:** Schema mismatch or unknown references fail fast.
- **Versioned:** Stored manifest versions tracked with timestamps.
- **Evaluated:** Each version is gated by a dev/held-out test suite.

### Runtime: Manifest → Agent

The compiler transforms a manifest into an executable LangGraph agent:

```
1. load_manifest_dict(raw_dict)        # Parse YAML, deserialize
2. resolve_manifest(manifest)          # Resolve all registry references
3. compile_agent(manifest, registries) # Build LangGraph StateGraph
   ├─ Create typed state (Pydantic)
   ├─ Add agent node (model call + tool dispatch)
   ├─ Add tool nodes (one per tool)
   ├─ Add router (decide: continue loop or answer)
   └─ Attach checkpointer (optional SQLite/Postgres)
4. agent.astream(input)                # Run, yield trace events
   └─ Each step emits TraceEvent (start, tool_call, etc.)
```

### LangGraph Runtime: The ReAct Loop

AgentForge uses **LangGraph** to orchestrate agent execution. The runtime implements the **ReAct pattern** (Reason + Act):

```mermaid
graph TD
    A["Input"] -->|user_input| B["Agent Node"]
    B -->|model.complete<br/>tools=all_tools| C{"Tool\nNeeded?"}
    C -->|yes| D["Tool Node"]
    D -->|tool result| B
    B -->|loop back| C
    C -->|no| E["Answer"]
    E --> F["Output"]
    
    G["Limits:\nmax_steps\nwall_clock_s\nmax_tokens"] -.->|enforce| B
    G -.->|enforce| D
    H["Memory<br/>Checkpointer"] -.->|persist<br/>thread state| B
    I["Trace Bus"] -.->|emit events| B
    I -.->|emit events| D
```

**Step-by-step:**
1. **Start:** User provides input (string)
2. **Agent node:** Call the model with all available tools
3. **Router:** Check the model's response
   - If tool calls → dispatch each tool (tool nodes run in parallel)
   - If no tool calls → done, return the answer
4. **Tool node:** Execute tool, capture output
5. **Loop:** Feed tool results back to agent, repeat until answer or limits hit
6. **Persist:** On every exit path (success, timeout, error, client disconnect), save the run with full trace
7. **Memory:** Before the first agent call, retrieve relevant memories; after answering, persist new facts

**Limits enforcement:**
- `max_steps`: agent loop counter; stop if exceeded
- `wall_clock_s`: wall-clock timeout; kill if exceeded
- `max_tokens_total`: cumulative token budget across all model calls; deny further calls if exceeded

### Token Streaming

The `/api/runs` endpoint returns Server-Sent Events (SSE). Token deltas stream in real-time:

```
Client                           Backend
  │                                │
  └──── POST /api/runs ────────────>
       (manifest, input)             │
                                     ├─ compile_agent()
                                     ├─ astream() begins
                                     │
        <────── run_started ─────────┤
        <───── step:start ───────────┤
        <─── tool_call:web_search ──┤
        <─── tool_result ────────────┤
        <── token:delta='hello' ─────┤ (live text)
        <── token:delta=' world' ────┤ (live text)
        <──── step:end ──────────────┤
        <─────── answer ─────────────┤
        <── done:cost_usd ───────────┤
                                     └─ Persist run
```

Events include type, timestamp, step index, and a detail payload (JSON). The frontend consumes these events to:
- Show tool calls and results in a sidebar
- Accumulate token deltas into the full answer text
- Build a trace for 3D replay

---

## Unified Agent Core: Modules & Interfaces

The core (`packages/agent-core/src/agent_core/`) is organized by responsibility:

### `schema.py` — Manifest & Agent Definitions
- `Manifest`: Pydantic model for the full agent specification
- `AgentRunConfig`: Runtime options (eval_mode, thread_id, limits)
- `Agent`: Compiled agent; holds the LangGraph graph and checkpointer

### `registry.py` — Pluggable Registries
A unified registry interface shared by all backends:

```python
class Registry(Protocol):
    def register(self, key: str, obj: Any) -> None: ...
    def get(self, key: str) -> Any: ...
    def list(self) -> list[str]: ...
```

Five registries:
1. **ToolRegistry:** BaseTool implementations (web_search, code_executor, etc.)
2. **ModelRegistry:** ModelProvider implementations (anthropic, openai, echo)
3. **MemoryRegistry:** MemoryProvider implementations (in_memory, mem0)
4. **PromptRegistry:** Prompt text/templates (loaded from files)
5. **MCPRegistry:** MCP server configs

### `interfaces.py` — Core Contracts
Every backend must implement one of these protocols:

```python
class BaseTool(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]  # Pydantic model
    async def run(self, **kwargs) -> ToolResult: ...

class ModelProvider(Protocol):
    async def complete(self, messages: list, tools: list, **cfg) -> ModelResponse: ...

class MemoryProvider(Protocol):
    async def add(self, scope: Scope, namespace: str, items: list[MemoryItem]) -> None: ...
    async def search(self, scope: Scope, namespace: str, query: str, k: int) -> list[MemoryItem]: ...
    async def delete(self, scope: Scope, namespace: str, ids: list[str]) -> None: ...

class CodeExecutor(Protocol):
    async def run(self, code: str, ctx: RunContext) -> ExecResult: ...

class MCPConnector(Protocol):
    async def discover(self, server_cfg) -> list[BaseTool]: ...
```

### `runtime.py` — LangGraph Compiler
- `compile_agent(manifest, registries)`: manifest → LangGraph StateGraph
  - Creates agent node (calls model)
  - Creates tool nodes (one per tool)
  - Wires router (tool dispatch or answer)
  - Attaches checkpointer (thread state persistence)
  - Returns compiled Agent

### `loader.py` — Manifest Loading
- `load_manifest_dict(raw_dict)`: Parse and validate against schema
- `resolve_manifest(manifest, registries)`: Verify all references exist in registries
- Fails fast with clear error messages on unknown tools, models, prompts, etc.

### `models/` — Model Providers
- `anthropic.py`: Claude models (Anthropic API)
- `openai.py`: GPT-4, GPT-4o (OpenAI API)
- `echo.py`: Offline echo for testing (no API key needed)

Each provider:
1. Takes messages and tool specs
2. Calls the API
3. Returns structured response (text + optional tool calls)
4. Tracks token usage

### `tools/` — Built-in Tools
Each tool is a `BaseTool` with args_schema validation:

- **`web_search.py`**: WebSearchTool (Tavily API)
  - Input: query string
  - Output: list of results (title, snippet, URL)
  - Use case: agents looking up current events or facts

- **`code_executor.py`**: CodeExecutorTool (wraps sandbox)
  - Input: Python code (string)
  - Output: stdout, stderr, return value
  - Enforces allow_network flag and timeouts
  - Use case: "coder" agents writing and executing scripts

- **`embedding_search.py`**: EmbeddingSearchTool (semantic search)
  - Input: query string
  - Output: top-k semantically similar documents
  - Indexes via `POST /api/index`
  - Use case: agents searching documentation or code

- **`http_fetch.py`**: HttpFetchTool
  - Input: URL, headers (optional)
  - Output: response body (text)
  - Use case: agents fetching API responses or web pages

### `memory/` — Long-Term Memory
Agents remember facts across sessions:

- **`in_memory.py`**: InMemoryMemoryProvider (default)
  - Stores MemoryItem objects in RAM
  - Full-text and embedding-based search
  - No persistence

- **`mem0_provider.py`**: Mem0MemoryProvider
  - Integrates mem0 semantic memory API
  - Stores facts with embeddings
  - Namespaced by user/agent/session
  - Persistent (external service)

Both implement `MemoryProvider`:
- `add(scope, namespace, items)`: Store facts
- `search(scope, namespace, query, k)`: Retrieve relevant facts
- `delete(scope, namespace, ids)`: Remove facts

**Memory flow in a run:**
1. After model compiles, retrieve top-k memories: `memory.search(scope, namespace, input_query, k=5)`
2. Inject memories into system prompt: `"Relevant prior knowledge: ..."`
3. Agent executes normally
4. After getting an answer, persist new facts: `memory.add(scope, namespace, [MemoryItem(text=learned_fact)])`
5. **Eval mode:** Memory is isolated (all operations no-op) for determinism

### `sandbox/` — Code Execution
Agents can execute code safely:

- **`docker_executor.py`**: DockerCodeExecutor
  - Spins up a Docker container per execution
  - Deny-by-default: no host FS, no network (unless opt-in)
  - CPU, memory, wall-clock time limits
  - Non-root user
  - Security matrix: 8 automated tests (all pass)

Implements `CodeExecutor.run(code, ctx)`:
- Returns `ExecResult`: stdout, stderr, return_value, exit_code, timed_out, artifacts

### `mcp/` — MCP Connector
Agents can use tools from external MCP servers:

- **`connector.py`**: MCPConnector
  - Connect to a server (stdio or HTTP)
  - Discover available tools
  - Adapt MCP tools to `BaseTool` interface
  - Register uniformly in ToolRegistry

**MCP flow:**
1. Manifest references `mcp_servers: [github_mcp]`
2. Compiler discovers: `mcp.discover(server_config)` → list[BaseTool]
3. Each tool auto-adapted to `BaseTool` with args_schema
4. Registered in tool registry
5. Agent can call them like any other tool

### `checkpoint.py` — Thread State Persistence
Agents can maintain conversation state across multiple runs:

- **Default (no checkpointer):** Each run is isolated; new `thread_id` per run
- **SQLite checkpointer:** Save thread state locally
- **Postgres checkpointer:** Share thread state across deployment

When a client provides a `thread_id`, subsequent runs resume the same conversation. Checkpointer saves:
- Message history
- Tool results
- Intermediate state

### `observability.py` — Trace Events
Every step emits a structured `TraceEvent`:

```python
class TraceEvent(BaseModel):
    type: str  # "step_start", "step_end", "tool_call", "tool_result", 
               #   "answer", "token", "error", "limit"
    step: int  # Loop iteration
    timestamp: str  # ISO 8601
    detail: dict  # Event-specific data (tool name, output, etc.)
    tokens: int | None  # Tokens used in this step
    latency_ms: int | None  # Wall-clock time
```

Emitted on every step, tool call, token delta, and terminal state. The API streams these over SSE to the frontend.

### `guardrails.py` — Safety Enforcement
Before a tool is called, guardrails can inspect and block:

- `NoSecretExfil`: Redact known secrets from tool inputs/outputs
- `TimeoutGuardrail`: Kill runs exceeding wall_clock_s
- Custom guardrails: extend the interface, register in GuardrailRegistry

### `eval.py` — Evaluation Harness
The LLM analog of train/val/test (see [Evaluation Harness](#evaluation-harness-dev--held-out-split) below).

### `run_store.py` & `eval_store.py` — Persistence
- **RunStore:** Save/load `RunRecord` (full trace, tokens, cost)
  - InMemoryRunStore (default, bounded, newest-first)
  - PostgresRunStore (optional, durable)
- **EvalReportStore:** Save/load `EvalReport` and promote baselines
  - InMemoryEvalReportStore (default)
  - PostgresEvalReportStore (optional)

### `manifest_store.py` — Manifest Versioning
Store and retrieve manifest versions:
- InMemoryManifestStore (default)
- PostgresManifestStore (optional)

Tracks: manifest_id, version number, YAML content, created_at

---

## Evaluation Harness: Dev / Held-Out Split

AgentForge implements **dev/held-out evaluation** — the LLM analog of train/validation/test in ML:

```
        Tasks
           │
      ┌────┴────┐
      │          │
    Dev Set   Held-Out Set
      │          │
      │      (never inspect)
      │          │
   Iterate    Baseline
   Prompts      Report
      │          │
      └────┬─────┘
           │
     Regression Gate?
```

### Concepts

**Dev Set:** Inspect freely while iterating prompts and tools. Fast feedback loop. Used to debug.

**Held-Out Set:** Sealed. Opened only to report final quality and detect regression. Prevents "prompt overfitting" (tuning to specific examples).

**Disjointness Check:** Dev and held-out sets must not overlap (exact or near-duplicate tasks). Automated check enforces this.

**Scoring Modes:**
1. **Programmatic:** Deterministic checks (e.g., "output JSON matches schema")
2. **Rubric:** Boolean assertions (e.g., "mentioned a source")
3. **LLM-as-judge:** Open-ended quality (e.g., "is the answer helpful?")
   - Fixed judge prompt + model + temperature 0
   - Human spot-check required (PRD §14.2)
   - Flagged for periodic audit

### Regression Gate

When a manifest is updated (prompt, tools, limits):

```
1. Run eval suite (dev + held-out) with new version
2. Compare held-out pass rate to baseline
3. If drop > tolerance (default 5%):
   ├─ Block promotion of the new version
   ├─ Show diff (what changed in the manifest)
   └─ Flag for investigation
4. If no regression:
   ├─ Report dev vs held-out side-by-side
   └─ Optionally promote to new baseline
```

### API

`POST /api/eval`:
```json
{
  "manifest": { ... },
  "suite_id": "suites/coder_v1",
  "baseline_held_out": { ... },  // Previous report (optional)
  "measure_flake": true          // Re-run to detect nondeterminism
}
```

Returns:
```json
{
  "report_id": "abc123...",
  "report": {
    "dev": {
      "pass_rate": 0.9,
      "scores": [...]
    },
    "held_out": {
      "pass_rate": 0.85,
      "scores": [...]
    }
  },
  "regression": {
    "blocked": true,
    "reason": "held-out pass rate dropped 0.10 (0.95 -> 0.85); tolerance 0.05"
  }
}
```

---

## Multi-Agent Supervisor

Agents can delegate to other agents:

```yaml
id: supervisor
model:
  provider: anthropic
  name: claude-sonnet-5
tools: []
sub_agents: [planner, coder, reviewer]
```

**How it works:**
1. Compiler recursively compiles sub_agents
2. Each sub-agent exposed as a tool: `ask_planner`, `ask_coder`, `ask_reviewer`
3. Supervisor can invoke them: "Let me ask the planner to break down the task"
4. Sub-agent results feed back into supervisor loop

**Safety:**
- Cycle detection: if A→B→A, fail at compile time
- Tool name collision guard: if two agents have the same id, error
- Sub-agent invocation counted in parent's step limit

---

## Guardrails & IO Schema

### Guardrails

Inspect every tool call before execution and block/redact unsafe patterns:

```python
class NoSecretExfilGuardrail:
    async def check(self, tool_name, args):
        if any(secret in str(args.values()) for secret in os.environ.values()):
            raise GuardrailError("secret detected in tool args")
```

Registered and applied per-manifest:
```yaml
guardrails: [no_secret_exfil, timeout_30s]
```

Shipped guardrails:
- `NoSecretExfil`: Redact known secrets from logs and traces
- `Timeout`: Enforce wall_clock_s limit

### IO Schema

Validate agent input and output against Pydantic models:

```yaml
io_schema:
  input: UserRequest   # Must deserialize to UserRequest
  output: AgentResult  # Must deserialize to AgentResult
```

If input doesn't match, fail early. If model output can't be parsed as AgentResult, error.

---

## Observability & Traces

Every run produces a complete trace: list of `TraceEvent` objects.

### Trace Storage

- **In-memory:** InMemoryRunStore (bounded, newest-first)
- **Postgres:** PostgresRunStore with configurable retention
  - Keep all traces for N days
  - For runs with >100 steps, sample (every Nth step)

### Trace Export

`GET /api/runs/{run_id}/export` returns the full `RunRecord`:
```json
{
  "id": "abc123",
  "manifest_id": "coder",
  "model": "claude-sonnet-5",
  "input": "write a function to sort a list",
  "status": "completed",
  "answer": "Here's a function...",
  "trace": [
    { "type": "step_start", "step": 0, ... },
    { "type": "tool_call", "tool": "web_search", ... },
    { "type": "tool_result", "output": "...", ... },
    { "type": "step_end", "step": 0, ... },
    { "type": "answer", "detail": "Here's a function...", ... }
  ],
  "usage": { "input_tokens": 150, "output_tokens": 300 },
  "cost_usd": 0.0045,
  "created_at": "2026-07-10T10:00:00Z"
}
```

### Cost Accounting

Tokens tracked at every step. Cost computed at end:

```
cost_usd = (input_tokens * price_per_input) + (output_tokens * price_per_output)
```

Prices per provider/model in a price table. Updated as API costs change.

---

## Frontend: Web UI Architecture

### Agent Builder Tab
- YAML editor with syntax highlighting and live validation
- Template gallery (examples: researcher, coder, supervisor)
- Run panel: stream events, show tool calls
- Run history: list, click to view full trace
- Dark/light theme toggle

### 3D Execution Graph
- **Three.js visualization** of the agent graph
  - Nodes: agent, tools, router
  - Edges: message passing, tool dispatch
  - Animation: nodes pulse on activation, edges highlight on messages
- **Timeline scrubber:** click a point in time to see the agent state at that step
- **Fallbacks:**
  - 2D SVG rendering if WebGL unavailable
  - Reduced-motion CSS media query respected (disables animations)
  - Keyboard navigation: arrow keys move between nodes

### Eval Panel
- Dev vs held-out pass rates (side-by-side bar charts)
- Task-level pass/fail breakdown
- Regression detection (↑/↓ indicator if compared to baseline)
- Promote to baseline (save this eval report as the new baseline)
- Export report as JSON

---

## Data Models (Persistence)

### RunRecord
```python
class RunRecord(BaseModel):
    id: str                    # uuid
    manifest_id: str           # agent id
    model: str                 # model name
    input: str
    status: str                # "completed", "error", "timeout", "incomplete"
    answer: str | None
    trace: list[TraceEvent]   # Full trace
    usage: dict                # input_tokens, output_tokens
    cost_usd: float
    created_at: str            # ISO 8601
```

### ManifestRecord
```python
class ManifestRecord(BaseModel):
    id: str                    # agent id
    version: int               # auto-incrementing
    manifest: dict             # Raw YAML/JSON
    created_at: str
```

### EvalReport
```python
class EvalReport(BaseModel):
    pass_rate: float           # % of tasks passed
    scores: list[dict]        # Per-task: input, expected, output, score, reason
    flake_rate: float         # % flakiness (re-run variance)

class DevHeldOutReport(BaseModel):
    dev: EvalReport
    held_out: EvalReport
```

### StoredBaseline
```python
class StoredBaseline(BaseModel):
    manifest_id: str
    held_out: EvalReport      # The baseline (always held-out)
    dev: EvalReport | None     # Optional dev snapshot
    source_report_id: str     # Which eval run this came from
    created_at: str
```

---

## Extension Points (No Core Edits)

### Add a Tool (15 min)
Implement `BaseTool`, register:
```python
class WeatherTool(BaseTool):
    name = "weather"
    args_schema = WeatherArgs
    async def run(self, city: str, **kwargs):
        return ToolResult(output=f"72°F in {city}")

registries.tools.register("weather", WeatherTool())
```

### Add a Model Provider
Implement `ModelProvider`, register:
```python
class LlamaProvider(ModelProvider):
    async def complete(self, messages, tools, **cfg):
        # Call Llama API
        return ModelResponse(...)

registries.models.register("llama", LlamaProvider())
```

### Add a Memory Backend
Implement `MemoryProvider`, register:
```python
class RedisMemory(MemoryProvider):
    async def add(self, scope, namespace, items):
        # Store in Redis
    async def search(self, scope, namespace, query, k):
        # Retrieve from Redis

registries.memory.register("redis", RedisMemory())
```

### Connect an MCP Server
Add config, connector discovers tools:
```python
mcp_config = {
    "server_type": "stdio",
    "command": ["python", "-m", "mcp_server_github"]
}
registries.mcp.register("github_mcp", mcp_config)
```

All happen without touching `packages/agent-core` code. Proven by the **extension-conformance test** (Phase 10).

---

## Deployment & Persistence

### Local Dev (Default)
- In-memory stores (runs, evals, manifests)
- SQLite checkpointer (per-run thread state)
- No persistence across restarts

### Production (Optional Postgres)
Set `DATABASE_URL`:
```bash
export DATABASE_URL=postgresql://user:pass@localhost/agentforge
```

The API auto-detects and uses:
- `PostgresRunStore` (durable run history)
- `PostgresManifestStore` (version history)
- `PostgresEvalReportStore` (eval reports + baselines)
- Postgres checkpointer (shared thread state across deployment)

---

## Security

### Sandbox
- Deny-by-default: no host FS, no network
- Resource limits: CPU shares, memory cap, wall-clock timeout
- Non-root user inside container
- Output size cap (stdout/stderr)
- Package allowlist (import restrictions)

Verified by 8 automated security tests in CI.

### Secret Redaction
- Before persisting: redact known secrets from traces
- In logs: scrub API keys, bearer tokens, etc.
- On the wire: SSE events scrubbed before streaming

### Auth (Phase 11, Partial)
- Optional `AGENTFORGE_API_KEY` (shared key)
- Rate limiting: 10 runs/minute per IP (configurable)
- Stateless key auth (no session tracking)

Per-user isolation (future):
- Per-user namespaces for runs, evals, manifests, memories
- Per-user rate limits
- Isolated eval reports

---

## Performance Characteristics

- **Sandbox run (simple script):** <3s p95
- **Trace streaming latency:** <100ms typical
- **Eval run (10 tasks):** 30–60s (depends on model latency)
- **3D graph replay:** instant (from cached trace)
- **Manifest compile:** <100ms

---

## Next Steps / Deferred

- **Per-user isolation** (Phase 11 future)
- **E2B sandbox backend** (Docker ships; E2B optional)
- **pgvector embeddings** (in-memory vector store ships; pgvector deferred)
- **Visual manifest builder** (YAML editor ships; drag-drop builder deferred)

---

*Last updated: 2026-07-10*
