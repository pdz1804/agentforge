# AgentForge API Reference

Complete HTTP API documentation for AgentForge. All endpoints run on the FastAPI backend (default port 8077).

**Base URL:** `http://localhost:8077` (or `API_PORT` if configured)

---

## Table of Contents

- [Health & Discovery](#health--discovery)
- [Agent Manifest CRUD & Versioning](#agent-manifest-crud--versioning)
- [Agent Runs (Live Streaming)](#agent-runs-live-streaming)
- [Evaluation Harness](#evaluation-harness)
- [Sandbox Code Execution](#sandbox-code-execution)
- [Memory Management](#memory-management)
- [Embedding Search](#embedding-search)
- [Tools & Suites Discovery](#tools--suites-discovery)
- [Error Handling](#error-handling)
- [Authentication & Rate Limits](#authentication--rate-limits)

---

## Health & Discovery

### GET /health

Check API health and list available tools and models.

**Response:**
```json
{
  "status": "ok",
  "core_version": "0.1.0",
  "tools": ["web_search", "code_executor", "embedding_search", "http_fetch"],
  "models": ["anthropic", "openai", "echo"]
}
```

**Use case:** Health checks, service discovery, frontend initialization.

---

## Agent Manifest CRUD & Versioning

### POST /api/agents/validate

Validate a manifest's schema and resolve all references (no storage).

**Request:**
```json
{
  "manifest": {
    "id": "my_agent",
    "version": 1,
    "model": {
      "provider": "echo",
      "name": "echo",
      "temperature": 0.2
    },
    "prompt_ref": "prompts/default",
    "tools": ["web_search"],
    "memory": { "provider": "in_memory" },
    "limits": { "max_steps": 10 }
  }
}
```

**Response (success):**
```json
{
  "ok": true,
  "id": "my_agent",
  "error": null
}
```

**Response (error):**
```json
{
  "ok": false,
  "id": null,
  "error": "unknown tool 'nonexistent' in registry"
}
```

**Status codes:**
- `200`: Valid manifest
- `200` with `ok: false`: Invalid manifest (validation error in detail)

---

### POST /api/agents

Create a new agent manifest (requires auth).

**Authentication:** `AGENTFORGE_API_KEY` if set

**Request:**
```json
{
  "manifest": { ... }  // Full manifest as above
}
```

**Response:**
```json
{
  "id": "my_agent",
  "version": 1,
  "manifest": { ... },
  "created_at": "2026-07-10T10:00:00Z"
}
```

**Status codes:**
- `200`: Created (first version assigned v1)
- `400`: Invalid manifest
- `403`: Missing API key (if required)

---

### GET /api/agents

List all stored agent manifests (requires auth).

**Query params:**
- None

**Response:**
```json
{
  "agents": [
    { "id": "my_agent", "latest_version": 3 },
    { "id": "researcher", "latest_version": 1 }
  ]
}
```

**Status codes:**
- `200`: Success
- `403`: Missing API key (if required)

---

### GET /api/agents/{manifest_id}

Fetch a specific agent manifest (latest version or specific version).

**Path params:**
- `manifest_id` (string): Agent ID

**Query params:**
- `version` (integer, optional): Specific version to fetch. If omitted, returns latest.

**Response:**
```json
{
  "id": "my_agent",
  "version": 3,
  "manifest": { ... },
  "created_at": "2026-07-10T10:30:00Z"
}
```

**Status codes:**
- `200`: Success
- `404`: Agent or version not found
- `403`: Missing API key (if required)

---

### PUT /api/agents/{manifest_id}

Update an agent manifest (saves as a new version).

**Path params:**
- `manifest_id` (string): Agent ID (must match manifest body)

**Request:**
```json
{
  "manifest": { ... }  // Full manifest with same id as path
}
```

**Response:**
```json
{
  "id": "my_agent",
  "version": 4,  // Auto-incremented
  "manifest": { ... },
  "created_at": "2026-07-10T11:00:00Z"
}
```

**Status codes:**
- `200`: Updated (new version created)
- `400`: Manifest id doesn't match path id, or invalid manifest
- `404`: Agent not found
- `403`: Missing API key (if required)

---

### GET /api/agents/{manifest_id}/versions

List all versions of an agent manifest.

**Path params:**
- `manifest_id` (string): Agent ID

**Response:**
```json
{
  "manifest_id": "my_agent",
  "versions": [
    {
      "version": 1,
      "manifest": { ... },
      "created_at": "2026-07-10T10:00:00Z"
    },
    {
      "version": 2,
      "manifest": { ... },
      "created_at": "2026-07-10T10:15:00Z"
    },
    {
      "version": 3,
      "manifest": { ... },
      "created_at": "2026-07-10T10:30:00Z"
    }
  ]
}
```

**Status codes:**
- `200`: Success
- `404`: Agent not found
- `403`: Missing API key (if required)

---

### GET /api/agents/{manifest_id}/diff

Show field-level and unified-text diff between two versions.

**Path params:**
- `manifest_id` (string): Agent ID

**Query params:**
- `from` (integer): Starting version
- `to` (integer): Ending version

**Example:** `GET /api/agents/my_agent/diff?from=1&to=3`

**Response:**
```json
{
  "manifest_id": "my_agent",
  "from_version": 1,
  "to_version": 3,
  "field_diffs": {
    "model.temperature": { "from": 0.1, "to": 0.5 },
    "tools": { "from": ["web_search"], "to": ["web_search", "code_executor"] }
  },
  "unified_diff": "--- version 1\n+++ version 3\n@@ ... @@\n- temperature: 0.1\n+ temperature: 0.5\n ..."
}
```

**Status codes:**
- `200`: Success
- `404`: Agent or version not found
- `403`: Missing API key (if required)

---

## Agent Runs (Live Streaming)

### POST /api/runs

Run an agent, streaming trace events as Server-Sent Events (SSE).

**Authentication:** `AGENTFORGE_API_KEY` if set, subject to `runs_rate_limit`

**Request:**
```json
{
  "manifest": { ... },             // Full manifest (inline)
  "input": "What is the weather?",
  "eval_mode": false,              // Optional: if true, use temp=0, isolate memory
  "thread_id": "session_123",      // Optional: resume a prior thread; if omitted, new thread per run
  "agents": [                       // Optional: sub-agent manifests for supervisor
    { "id": "planner", ... },
    { "id": "coder", ... }
  ]
}
```

**Response:** Server-Sent Events (streaming)

Each event is a single-line JSON object prefixed with `data: `:

```
data: {"type": "run_started", "run_id": "abc123..."}

data: {"type": "step_start", "step": 0, "timestamp": "2026-07-10T10:00:00Z"}

data: {"type": "tool_call", "step": 0, "tool": "web_search", "args": {"query": "weather today"}}

data: {"type": "tool_result", "step": 0, "tool": "web_search", "output": "Clear skies, 72°F"}

data: {"type": "token", "step": 1, "detail": "The"}

data: {"type": "token", "step": 1, "detail": " weather"}

data: {"type": "step_end", "step": 1, "latency_ms": 450, "tokens": 50}

data: {"type": "answer", "detail": "The weather today is clear skies, 72°F"}

data: {"type": "done", "run_id": "abc123...", "cost_usd": 0.0045}
```

**Event types:**

| Type | Fields | Meaning |
|---|---|---|
| `run_started` | `run_id` | Run initialized, streaming begins |
| `step_start` | `step`, `timestamp` | Agent loop iteration starting |
| `tool_call` | `step`, `tool`, `args` | Tool invoked with arguments |
| `tool_result` | `step`, `tool`, `output` | Tool returned result |
| `token` | `step`, `detail` | Single token delta (live text) |
| `step_end` | `step`, `latency_ms`, `tokens` | Agent loop iteration complete |
| `answer` | `detail` | Final agent answer (one answer event) |
| `limit` | `detail` | Hit a limit (max_steps, wall_clock_s, max_tokens) |
| `error` | `detail` | Error occurred (run halted) |
| `done` | `run_id`, `cost_usd` | Stream complete, run persisted |

**Status codes:**
- `200`: Stream opens successfully (events flow until done or error)
- `400`: Invalid manifest
- `429`: Rate limit exceeded
- `403`: Missing API key (if required)

**Notes:**
- The client should connect to this endpoint with an SSE listener
- `token` events are live deltas (stream as they arrive); the final `answer` event contains the full text
- `token` events are not persisted in the trace; only non-token events are stored
- If the client disconnects, the run still persists (saved in the finally block)

---

### GET /api/runs

List all stored runs (newest first, paginated).

**Authentication:** `AGENTFORGE_API_KEY` if set

**Query params:**
- `limit` (integer, default 50): Max runs to return

**Response:**
```json
{
  "runs": [
    {
      "id": "abc123...",
      "manifest_id": "my_agent",
      "model": "claude-sonnet-5",
      "status": "completed",
      "cost_usd": 0.0045,
      "created_at": "2026-07-10T10:00:00Z",
      "answer": "The weather today is clear..."
    },
    {
      "id": "def456...",
      "manifest_id": "researcher",
      "model": "gpt-4o",
      "status": "error",
      "cost_usd": 0.0012,
      "created_at": "2026-07-10T09:50:00Z",
      "answer": null
    }
  ]
}
```

**Status codes:**
- `200`: Success
- `403`: Missing API key (if required)

---

### GET /api/runs/{run_id}

Fetch a specific run with full trace.

**Path params:**
- `run_id` (string): Run ID (UUID hex)

**Response:**
```json
{
  "id": "abc123...",
  "manifest_id": "my_agent",
  "model": "claude-sonnet-5",
  "input": "What is the weather?",
  "status": "completed",
  "answer": "The weather today is clear...",
  "trace": [
    { "type": "step_start", "step": 0, ... },
    { "type": "tool_call", "step": 0, "tool": "web_search", ... },
    { "type": "tool_result", "step": 0, "tool": "web_search", "output": "..." },
    { "type": "step_end", "step": 0, ... },
    { "type": "answer", "detail": "..." }
  ],
  "usage": {
    "input_tokens": 150,
    "output_tokens": 300
  },
  "cost_usd": 0.0045,
  "created_at": "2026-07-10T10:00:00Z"
}
```

**Status codes:**
- `200`: Success
- `404`: Run not found
- `403`: Missing API key (if required)

---

### GET /api/runs/{run_id}/export

Export a run as JSON (same as GET /api/runs/{run_id}).

**Path params:**
- `run_id` (string): Run ID

**Response:** Full `RunRecord` (JSON)

**Status codes:**
- `200`: Success
- `404`: Run not found
- `403`: Missing API key (if required)

---

## Evaluation Harness

### GET /api/suites

List available dev/held-out suite pairs.

**Query params:** None

**Response:**
```json
{
  "suites": [
    {
      "suite_id": "suites/coder_v1",
      "manifest_id": "coder",
      "dev_task_count": 20,
      "held_out_task_count": 30
    },
    {
      "suite_id": "suites/researcher_v2",
      "manifest_id": "researcher",
      "dev_task_count": 15,
      "held_out_task_count": 25
    }
  ]
}
```

**Status codes:** `200`

---

### POST /api/eval

Run a manifest against dev + held-out test suites.

**Authentication:** `AGENTFORGE_API_KEY` if set, subject to `eval_rate_limit`

**Request (variant 1: suite ID):**
```json
{
  "manifest": { ... },
  "suite_id": "suites/coder_v1",
  "measure_flake": true,
  "use_stored_baseline": true
}
```

**Request (variant 2: inline suites):**
```json
{
  "manifest": { ... },
  "dev_suite": {
    "id": "coder_dev",
    "manifest_id": "coder",
    "tasks": [
      {
        "input": "write a function to sort a list",
        "expected": { "type": "code", "language": "python" },
        "scoring_mode": "programmatic"
      }
    ]
  },
  "held_out_suite": {
    "id": "coder_heldout",
    "manifest_id": "coder",
    "tasks": [ ... ]
  },
  "measure_flake": true
}
```

**Request (variant 3: with baseline for regression gating):**
```json
{
  "manifest": { ... },
  "suite_id": "suites/coder_v1",
  "baseline_held_out": { ... },  // Previous EvalReport
  "baseline_dev": { ... },       // Optional
  "regression_tolerance": 0.05   // Allow 5% drop
}
```

**Response:**
```json
{
  "report_id": "report_xyz...",
  "report": {
    "dev": {
      "pass_rate": 0.90,
      "flake_rate": 0.0,
      "scores": [
        {
          "task_input": "write a function to sort a list",
          "expected": { ... },
          "agent_output": "def sort(lst): ...",
          "score": 1.0,
          "reason": "output is valid Python code"
        }
      ]
    },
    "held_out": {
      "pass_rate": 0.85,
      "flake_rate": 0.02,
      "scores": [ ... ]
    }
  },
  "regression": {
    "blocked": false,
    "held_out_rate_change": 0.0,
    "dev_rate_change": -0.05,
    "message": "held-out stable; dev slightly degraded (expected)"
  }
}
```

**Status codes:**
- `200`: Success
- `400`: Invalid manifest or suites
- `404`: Suite not found (if using `suite_id`)
- `429`: Rate limit exceeded
- `403`: Missing API key (if required)

**Notes:**
- Each task runs in `eval_mode`: temperature 0, memory isolated, determinism maximized
- `measure_flake`: if true, each task re-run to detect nondeterminism (flake_rate)
- Regression gate: if drop > tolerance on held-out, `blocked: true` and a reason
- LLM-as-judge tasks use a fixed judge model + temp 0; human spot-checks required

---

### GET /api/eval/{report_id}

Fetch a previously stored eval report.

**Path params:**
- `report_id` (string): Report UUID

**Response:**
```json
{
  "report_id": "report_xyz...",
  "manifest_id": "coder",
  "manifest_version": 3,
  "created_at": "2026-07-10T10:00:00Z",
  "report": { ... }  // DevHeldOutReport
}
```

**Status codes:**
- `200`: Success
- `404`: Report not found
- `403`: Missing API key (if required)

---

### GET /api/eval/{report_id}/spot-check

List LLM-as-judge tasks queued for human audit.

**Path params:**
- `report_id` (string): Report UUID

**Response:**
```json
{
  "report_id": "report_xyz...",
  "manifest_id": "coder",
  "samples": [
    {
      "task_input": "write a sorting function",
      "expected_outcome": { ... },
      "agent_output": "def sort(lst): ...",
      "judge_score": 0.8,
      "judge_reason": "code is correct but not optimally efficient"
    }
  ]
}
```

**Status codes:**
- `200`: Success (empty `samples` if no judge tasks)
- `404`: Report not found
- `403`: Missing API key (if required)

---

### POST /api/eval/{report_id}/promote

Promote an eval report's held-out results to the baseline for future regression gating.

**Path params:**
- `report_id` (string): Report UUID

**Response:**
```json
{
  "manifest_id": "coder",
  "source_report_id": "report_xyz...",
  "baseline_pass_rate": 0.85
}
```

**Status codes:**
- `200`: Success
- `404`: Report not found
- `403`: Missing API key (if required)

**Notes:**
- After promotion, subsequent eval runs can use `use_stored_baseline: true` to gate against this baseline
- Only the held-out results are stored as baseline; future regression gates compare against held-out

---

## Sandbox Code Execution

### POST /api/sandbox/exec

Execute Python code in an isolated Docker sandbox.

**Authentication:** `AGENTFORGE_API_KEY` if set, subject to `sandbox_rate_limit`

**Request:**
```json
{
  "code": "import json\nresult = [1, 2, 3]\nprint(json.dumps(result))",
  "timeout_s": 15
}
```

**Response:**
```json
{
  "stdout": "[1, 2, 3]\n",
  "stderr": "",
  "return_value": null,
  "exit_code": 0,
  "timed_out": false,
  "artifacts": []
}
```

**Status codes:**
- `200`: Success (even if code errored; check `exit_code`)
- `400`: Invalid request
- `503`: Sandbox unavailable (Docker not running)
- `429`: Rate limit exceeded
- `403`: Missing API key (if required)

**Notes:**
- Network is always denied (no egress)
- Host filesystem access denied
- CPU/memory/time limits enforced
- Non-root user; low privilege capabilities
- Package allowlist: approved imports only
- Secrets in stdout/stderr redacted before response

---

## Memory Management

### GET /api/memory

List stored memories (with optional search).

**Authentication:** `AGENTFORGE_API_KEY` if set

**Query params:**
- `provider` (string, default "in_memory"): Memory provider (in_memory, mem0)
- `scope` (string, default "user"): Scope (user, agent, session)
- `namespace` (string, default "default"): Namespace
- `query` (string, optional): Search query; if provided, return top-k matches

**Response:**
```json
{
  "items": [
    {
      "id": "mem_123",
      "text": "User prefers Python over JavaScript",
      "embedding": [0.1, 0.2, ...],
      "created_at": "2026-07-10T10:00:00Z"
    }
  ]
}
```

**Status codes:**
- `200`: Success
- `400`: Invalid scope
- `403`: Missing API key (if required)

---

### POST /api/memory

Add a memory item.

**Authentication:** `AGENTFORGE_API_KEY` if set

**Request:**
```json
{
  "text": "User prefers Python over JavaScript",
  "provider": "in_memory",
  "scope": "user",
  "namespace": "default"
}
```

**Response:**
```json
{
  "ok": true
}
```

**Status codes:**
- `200`: Success
- `400`: Invalid scope or provider
- `403`: Missing API key (if required)

---

### DELETE /api/memory

Delete memory items by ID.

**Authentication:** `AGENTFORGE_API_KEY` if set

**Query params:**
- `id` (string): Memory ID
- `provider` (string, default "in_memory"): Memory provider
- `scope` (string, default "user"): Scope
- `namespace` (string, default "default"): Namespace

**Response:**
```json
{
  "ok": true
}
```

**Status codes:**
- `200`: Success
- `400`: Invalid scope
- `403`: Missing API key (if required)

---

## Embedding Search

### POST /api/index

Index a document for semantic search.

**Authentication:** `AGENTFORGE_API_KEY` if set

**Request:**
```json
{
  "doc_id": "python_docs_001",
  "text": "Python's list.sort() method sorts in-place..."
}
```

**Response:**
```json
{
  "ok": true,
  "doc_id": "python_docs_001"
}
```

**Status codes:**
- `200`: Success
- `400`: Invalid request or embedding service error
- `403`: Missing API key (if required)

**Notes:**
- Requires `OPENAI_API_KEY` (embeddings via OpenAI)
- Documents indexed once are available for `embedding_search` tool queries

---

## Tools & Suites Discovery

### GET /api/tools

List all available tools.

**Query params:** None

**Response:**
```json
{
  "tools": ["web_search", "code_executor", "embedding_search", "http_fetch"]
}
```

**Status codes:** `200`

---

## Error Handling

### Error Response Format

All error responses (except SSE streams) follow this format:

```json
{
  "detail": "human-readable error message"
}
```

### Common HTTP Status Codes

| Code | Meaning |
|---|---|
| `200` | Success |
| `400` | Bad request (invalid JSON, validation error, unknown reference) |
| `403` | Forbidden (missing/invalid API key) |
| `404` | Not found (agent, run, report, etc. does not exist) |
| `422` | Unprocessable entity (malformed baseline in eval) |
| `429` | Too many requests (rate limit exceeded) |
| `500` | Internal server error |
| `503` | Service unavailable (e.g., sandbox Docker not running) |

### SSE Error Events

On `/api/runs`, errors are streamed as events:

```
data: {"type": "error", "detail": "unknown tool 'weather' in registry"}
```

The stream closes after an error event.

---

## Authentication & Rate Limits

### Optional API Key Auth

If `AGENTFORGE_API_KEY` is set, these endpoints require the key:

**Protected endpoints:**
- `POST /api/agents` (create)
- `GET /api/agents` (list)
- `GET /api/agents/{id}` (get)
- `PUT /api/agents/{id}` (update)
- `GET /api/agents/{id}/versions` (versions)
- `GET /api/agents/{id}/diff` (diff)
- `POST /api/runs` (run)
- `GET /api/runs` (list)
- `GET /api/runs/{id}` (get)
- `GET /api/runs/{id}/export` (export)
- `POST /api/eval` (eval)
- `GET /api/eval/{id}` (get report)
- `GET /api/eval/{id}/spot-check` (spot check)
- `POST /api/eval/{id}/promote` (promote baseline)
- `POST /api/sandbox/exec` (sandbox)
- `GET /api/memory` (list)
- `POST /api/memory` (add)
- `DELETE /api/memory` (delete)
- `POST /api/index` (index)

**Unprotected endpoints:**
- `GET /health`
- `GET /api/tools`
- `POST /api/agents/validate`
- `GET /api/suites`

**How to pass the key:**
Header: `Authorization: Bearer <AGENTFORGE_API_KEY>`

### Rate Limiting

If `AGENTFORGE_API_KEY` is set:
- `POST /api/runs`: 10 per minute per IP
- `POST /api/eval`: 5 per minute per IP
- `POST /api/sandbox/exec`: 10 per minute per IP

**Response on limit exceeded:**
```
HTTP 429 Too Many Requests
```

---

## Example: Full Agent Run Workflow

```bash
# 1. Validate a manifest (no auth needed)
curl -X POST http://localhost:8077/api/agents/validate \
  -H "Content-Type: application/json" \
  -d '{
    "manifest": {
      "id": "demo",
      "model": { "provider": "echo", "name": "echo", "temperature": 0.2 },
      "prompt_ref": "prompts/default",
      "tools": ["web_search"],
      "memory": { "provider": "in_memory" },
      "limits": { "max_steps": 10 }
    }
  }'

# 2. Run the agent (SSE stream)
curl -X POST http://localhost:8077/api/runs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "manifest": { ... },
    "input": "What is the weather?"
  }'

# (Server streams events; client receives run_started, step_start, tool_call, etc.)

# 3. List runs
curl http://localhost:8077/api/runs \
  -H "Authorization: Bearer YOUR_API_KEY"

# 4. Get a specific run with full trace
curl http://localhost:8077/api/runs/{run_id} \
  -H "Authorization: Bearer YOUR_API_KEY"

# 5. Export as JSON
curl http://localhost:8077/api/runs/{run_id}/export \
  -H "Authorization: Bearer YOUR_API_KEY" > run.json
```

---

*Last updated: 2026-07-10*
