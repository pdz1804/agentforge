# PRD — AgentForge: Multi-Agent Workbench & Code Sandbox

| Field | Value |
|---|---|
| Product | AgentForge |
| Version | 1.1 (Draft — adds agent-eval discipline + sandbox/security testing) |
| Author | ClaudeKit Engineer |
| Date | 2026-07-06 |
| Status | Planning / For review |
| Type | Learning-oriented full-stack AI product |
| Related | `../floralens/PRD.md` (consumer of the Unified Agent Core specified here §8) |

---

## 1. Executive Summary

AgentForge is a web workbench for **building, running, observing, and extending multi-agent AI systems**. You declare agents (tools, MCP connections, prompts, memory, model config) in a **single unified schema**, orchestrate them with LangGraph, let them **run code safely in a sandbox**, give them **long-term memory (mem0)** and **web search**, and watch execution as a **live 3D graph (Three.js)**.

AgentForge is the flagship home of the **Unified Agent Core** — the robust, extensible harness the user asked for: "everything defined in a unified way such that extension later is easy without redesign, extendable to many scopes." FloraLens consumes this exact core, proving reuse across domains.

**Honesty note on "training/validation/testing":** AgentForge does **not** fine-tune an LLM — it uses hosted models via a provider interface. The correct analog here is **agent evaluation**: a task-suite harness with a **dev/held-out split** that plays the same role train/val/test play in ML — you iterate prompts/manifests on the **dev** set and report quality on a **held-out** set you never tuned against. This prevents "prompt overfitting." That discipline, plus the **sandbox security test matrix** and the **software test pyramid**, is specified in §14.

## 2. Problem Statement & Learning Goals

**Problem.** Building multi-agent systems usually means ad-hoc glue: each agent wires its own tools, prompts, memory, and model differently, so adding a capability means re-plumbing. There's no single place to define an agent completely, run it safely, evaluate it honestly, and *see* what it did.

**Engineering learning goals (first-class driver).**

| Feature | Skill exercised |
|---|---|
| Unified agent manifest (tools+mcp+prompts+memory+model) | Harness design, robust/extensible architecture |
| Add a tool/agent/MCP with zero core edits | Plugin registries, interface design |
| Sandboxed code execution | Secure code sandbox (E2B/Docker/Firecracker) |
| LangGraph orchestration + supervisor/subagents | Multi-agent workflows |
| Long-term memory | mem0 |
| Web search & MCP tools | Tool interface, MCP integration |
| **Agent evaluation harness (dev/held-out split)** | **Correct "validation/testing" for LLM systems, regression gating** |
| Live 3D execution graph | Three.js / WebGL |
| Code/doc embedding search | Embeddings + vector search (shared skill w/ FloraLens) |

## 3. Target Users & Personas

- **Builder / Us (primary).** Compose agents fast, safely test tool-using/code-running agents, evaluate them, and extend without redesign.
- **AI-curious developer (secondary).** Wants a visual, understandable view of how multi-agent systems execute and where they fail.
- **Reviewer/observer (tertiary).** Inspects traces, memory, eval scores, and sandbox outputs to reason about agent behavior.

## 4. Goals & Non-Goals

**Goals**
- A single declarative **Agent Manifest** fully specifying an agent; loadable at runtime.
- Pluggable **registries** (Tools, Prompts, MCP, Memory, Model) — add capability via interface + registration, no core changes.
- **Safe sandbox** to execute agent-generated code with resource/time limits and no host access.
- **LangGraph** multi-agent orchestration with streaming traces.
- **mem0** long-term memory + thread checkpointer short-term memory.
- **MCP** connector surfacing external MCP tools uniformly into the tool registry.
- **Agent evaluation harness** with dev/held-out split, deterministic runs, and regression gating.
- **Three.js** live visualization of the agent graph + execution trace.

**Non-Goals (v1)**
- Fine-tuning LLMs (hosted models via provider interface only).
- Public marketplace / sharing of agents.
- Arbitrary untrusted multi-tenant sandbox at scale (single-tenant/self-host focus for v1).
- Mobile native apps.

## 5. Success Metrics

| Metric | Target (v1) |
|---|---|
| Add a new tool usable by an agent | ≤ 15 min, zero core-file edits |
| Add a new agent (manifest only) | ≤ 30 min, no code |
| Connect an MCP server & call its tool | ≤ 20 min via config |
| Sandbox blocks host FS/network by default | 100% (verified by escape-test matrix §14.4) |
| Sandbox run round-trip (simple script) | ≤ 3 s p95 |
| Execution trace fully reconstructable in 3D | 100% of runs |
| **Agent eval: held-out task pass rate** | **≥ agreed baseline; no regression on manifest/prompt change** |
| **Eval determinism (temp=0 runs)** | **stable pass/fail across repeats (flake rate < 5%)** |
| FloraLens runs on the same core unchanged | Verified (cross-product reuse) |

## 6. Functional Requirements

### Epic A — Unified Agent Core (the harness)
- **A1.** Agent Manifest schema (YAML/JSON, Pydantic-validated): id, model config, prompt_ref, tools[], mcp_servers[], memory config, sub_agents[], guardrails[], io_schema, limits.
- **A2.** Registries with a common `register()/get()/list()` contract: Tool/Prompt/MCP/Memory/Model.
- **A3.** `BaseTool` interface: name, description, args schema (Pydantic), `run()`; auto-exposed to the LLM.
- **A4.** Runtime compiles a manifest → LangGraph `StateGraph` with typed state + checkpointer.
- **A5.** Validation: manifest referencing unknown tool/prompt/mcp fails fast with a clear error.
- **A6.** Extension guarantee test: add tool/agent/MCP without editing core packages.

### Epic B — Agent Builder UI
- **B1.** Form/YAML editor to author a manifest; live validation; template gallery.
- **B2.** Wire sub-agents visually (supervisor + children); attach tools/memory.
- **B3.** "Run" panel: send input, stream output + tool-call trace.
- **B4.** Version manifests; diff between versions.

### Epic C — Code Sandbox
- **C1.** Execute agent-/user-provided code (Python first) in an isolated sandbox (E2B or Docker/Firecracker) — no host FS/network by default, CPU/mem/time limits.
- **C2.** Capture stdout/stderr, return values, artifacts; stream logs.
- **C3.** Expose sandbox to agents as a `CodeExecutorTool` (a "coder" agent can run code).
- **C4.** Guardrails: package allowlist, kill on timeout, size caps, redact secrets from logs.

### Epic D — Memory (mem0)
- **D1.** `MemoryProvider` interface; mem0 impl for long-term semantic memory (per user + per agent namespace).
- **D2.** Short-term thread state via LangGraph checkpointer (Postgres/SQLite).
- **D3.** Memory inspector UI: view/search/edit/delete; scope filters (user/agent/session).

### Epic E — MCP & External Tools
- **E1.** MCP connector: configure a server (stdio/HTTP), discover tools, adapt to `BaseTool`, register uniformly.
- **E2.** Built-in tools: WebSearchTool, CodeExecutorTool, EmbeddingSearchTool (shared w/ FloraLens), HttpFetchTool.
- **E3.** Per-agent tool allowlist (an agent sees only tools it declares).

### Epic F — Live 3D Execution Graph (Three.js)
- **F1.** Render the agent graph as 3D nodes (supervisor/sub-agents/tools) + edges.
- **F2.** During a run, nodes animate on activation; edges pulse on message/tool calls; click a node → inspect input/output/trace.
- **F3.** Timeline scrubber replays a run; reduced-motion + no-WebGL fallback (2D graph).

### Epic G — Observability & Traces
- **G1.** Every run produces a structured trace (steps, tool calls, tokens, latency, errors).
- **G2.** Trace viewer (list + 3D); export trace JSON.
- **G3.** Cost/token accounting per run and per agent.

### Epic H — Agent Evaluation Harness
- **H1.** Define **eval task suites**: each task = input + expected outcome/rubric + scoring mode.
- **H2.** **Dev vs held-out split** of tasks (§14.1): iterate on dev, report on held-out.
- **H3.** Scoring modes: programmatic/exact, rubric checks, and **LLM-as-judge** (with mandatory human spot-check + judge-bias caveats).
- **H4.** **Deterministic eval runs** (temperature 0, fixed seeds where supported) so pass/fail is stable.
- **H5.** **Regression gate:** editing a manifest/prompt re-runs the suite; a drop on held-out pass rate blocks promotion of that manifest version.
- **H6.** Eval report artifact per manifest version (dev + held-out side by side).

### Epic I — Platform
- **I1.** Auth + per-user isolation.
- **I2.** Persistence for manifests, runs, traces, memories, eval reports.
- **I3.** Rate limits; secret management (env/vault, never in committed manifests).

## 7. Representative User Stories & Acceptance Criteria

- **US-1 (A/E):** *Add a `weather` tool; an agent uses it — no core edit.*
  - AC: implement `BaseTool`, register, reference in manifest; agent calls it; zero diff in core files.
- **US-2 (C):** *A "coder" agent runs code in the sandbox and returns a result.*
  - AC: code runs isolated (no host FS/net); output streamed; timeout kills runaway code; escape-test matrix blocked.
- **US-3 (F):** *Watch the 3D graph light up during a run, then replay it.*
  - AC: nodes/edges animate live; click shows I/O; scrubber replays; fallbacks exist.
- **US-4 (D):** *An agent remembers facts across sessions.*
  - AC: mem0 stores + retrieves; inspector shows/edits/deletes; new session recalls prior facts.
- **US-5 (E):** *Connect an MCP server; its tools appear to agents.*
  - AC: config server; tools listed in registry; agent invokes one successfully.
- **US-6 (reuse):** *FloraLens's naturalist agents run on this exact core.*
  - AC: FloraLens manifests load/run against `packages/agent-core` with no core changes.
- **US-7 (H, eval correctness):** *A prompt change that quietly degrades quality is caught.*
  - AC: editing a manifest re-runs the eval suite; a held-out pass-rate drop beyond tolerance blocks the version and shows the diff; dev-only improvements that don't hold out are flagged.

## 8. Unified Agent Core — Full Specification (the harness)

> The robust, extensible core the user emphasized. FloraLens consumes it (its PRD §9 references this).

### 8.1 Design principles
- **Declarative first:** an agent is data (a manifest), not bespoke code.
- **Everything pluggable via interfaces + registries:** tools, prompts, MCP, memory, models.
- **Extension without redesign:** new capability = implement an interface + register; never edit core.
- **Typed + validated:** Pydantic schemas everywhere; fail fast with clear errors.
- **Observable + evaluable:** every step emits a trace event; every manifest version is eval-gated.

### 8.2 Agent Manifest (canonical schema)
```yaml
id: coder_supervisor
version: 3
model:
  provider: anthropic          # ModelProvider registry key
  name: claude-sonnet-5
  temperature: 0.2             # eval runs override to 0 for determinism
  max_tokens: 4096
prompt_ref: prompts/coder_supervisor.md    # PromptRegistry key/path
memory:
  provider: mem0               # MemoryProvider registry key
  scope: user                  # user | agent | session
  namespace: agentforge
tools: [web_search, code_executor]          # ToolRegistry keys (allowlist)
mcp_servers: [github_mcp]                    # MCPRegistry keys
sub_agents: [planner, coder, reviewer]       # other manifest ids
guardrails: [no_secret_exfil, timeout_30s]   # GuardrailRegistry keys
io_schema:
  input: CoderRequest          # Pydantic model
  output: CoderResult
limits: { max_steps: 20, max_tokens_total: 200000, wall_clock_s: 120 }
eval_suite: suites/coder_v1     # H: task suite this manifest is gated against
```

### 8.3 Core interfaces (Python, illustrative)
```python
class BaseTool(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]
    async def run(self, **kwargs) -> ToolResult: ...

class MemoryProvider(Protocol):
    async def add(self, scope: Scope, items: list[MemoryItem]) -> None: ...
    async def search(self, scope: Scope, query: str, k: int) -> list[MemoryItem]: ...
    async def delete(self, scope: Scope, ids: list[str]) -> None: ...

class ModelProvider(Protocol):
    async def complete(self, messages, tools, **cfg) -> ModelResponse: ...

class MCPConnector(Protocol):
    async def discover(self, server_cfg) -> list[BaseTool]: ...

class CodeExecutor(Protocol):
    async def run(self, code: str, ctx: RunContext) -> ExecResult: ...

class Registry(Protocol):
    def register(self, key: str, obj) -> None: ...
    def get(self, key: str): ...
    def list(self) -> list[str]: ...
```

### 8.4 Runtime
- Manifest → **compiler** resolves refs from registries → builds a LangGraph `StateGraph`.
- **Typed state** (Pydantic) threaded through nodes; **checkpointer** persists thread state.
- **Supervisor pattern:** router node decides next sub-agent/tool; loop until answer or limits.
- Each node emits **trace events** (start/end, tokens, tool I/O, errors) to the trace bus.
- **Eval mode:** runtime accepts an override (temp=0, fixed seeds, memory isolated) for deterministic evaluation.

### 8.5 Extension model (the guarantee)
| To add… | You do… | Core edits |
|---|---|---|
| A tool | implement `BaseTool`, `ToolRegistry.register("x", tool)` | none |
| An agent | write a manifest YAML, reference registered keys | none |
| An MCP server | add config entry; connector auto-adapts tools | none |
| A memory backend | implement `MemoryProvider`, register | none |
| A model provider | implement `ModelProvider`, register | none |
| A guardrail | implement guardrail, register | none |
| An eval suite | add task files under `suites/`, reference in manifest | none |

### 8.6 Packaging
- Shipped as `packages/agent-core` (installable Python package); AgentForge + FloraLens depend on it. Semantic-versioned public interfaces.

## 9. System Architecture

```
┌───────────────── Frontend (Next.js + React + Three.js) ─────────────────┐
│  Agent Builder │ Run Panel (SSE) │ 3D Execution Graph │ Traces │ Eval    │
└─────────┬───────────────┬───────────────────┬────────────────┬─────────┘
          │ REST/SSE       │                   │ trace stream   │ eval reports
┌─────────▼────────────────▼───────────────────▼────────────────▼─────────┐
│                         Backend API (FastAPI, Python)                    │
│  /agents /runs(SSE) /tools /mcp /memory /sandbox /traces /eval /auth     │
├──────────────────────────────────────────────────────────────────────────┤
│                    packages/agent-core (Unified Agent Core)              │
│   Manifest loader/validator │ Registries │ LangGraph runtime │ Trace bus │
│   Eval harness │ Tools: web_search, code_executor, embedding_search,...  │
│   MCP connector │ Memory (mem0) │ Model providers │ Guardrails            │
├───────────────┬──────────────────────┬─────────────────┬─────────────────┤
│  Sandbox svc  │  Vector DB           │  mem0 store     │  Postgres        │
│ (E2B/Docker/  │ (code/doc embeddings)│ (long-term)     │ (manifests/runs/ │
│  Firecracker) │                      │                 │  traces/evals)   │
└───────────────┴──────────────────────┴─────────────────┴─────────────────┘
                         │ stdio/HTTP
                  ┌──────▼───────┐
                  │  MCP servers │ (external tools)
                  └──────────────┘
```

## 10. Data Model (core entities)

- **User**(id, email, auth)
- **AgentManifest**(id, version, yaml, io_schema_ref, eval_suite_ref, created_at)
- **Run**(id, manifest_id, user_id, input_json, status, started_at, finished_at)
- **TraceEvent**(id, run_id, step, type, node, payload_json, tokens, latency_ms)
- **SandboxJob**(id, run_id, code, status, stdout, stderr, artifacts, exit_code, limits)
- **McpServer**(id, name, transport, config_json)
- **EvalSuite**(id, name, tasks_ref, split_manifest) — dev/held-out split
- **EvalReport**(id, manifest_id, manifest_version, split, pass_rate, scores_json, artifact_ref)
- **Memory** (managed by mem0; namespaced by user/agent)

## 11. API Surface (representative)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/agents` | list/create manifests |
| POST | `/api/agents/{id}/validate` | validate refs & schema |
| POST | `/api/runs` (SSE) | run an agent, stream output + trace |
| GET | `/api/runs/{id}/trace` | fetch trace (for 3D replay) |
| GET/POST | `/api/tools` `/api/mcp` | list tools / manage MCP servers |
| POST | `/api/sandbox/exec` | run code in sandbox (also used internally by tool) |
| POST | `/api/eval/{manifest_id}` | run eval suite; returns dev+held-out report |
| GET | `/api/eval/{manifest_id}/report` | fetch latest eval report |
| GET/DELETE | `/api/memory` | inspect/delete memories |

## 12. Non-Functional Requirements

- **Security (critical):** sandbox denies host FS/network by default; resource+time limits; package allowlist; secrets never in manifests or logs; **escape/DoS test matrix in CI** (§14.4).
- **Performance:** sandbox simple run ≤ 3 s p95; trace streaming low-latency.
- **Extensibility:** documented interfaces; adding capability requires no core edits (enforced by an extension test).
- **Reliability:** run limits (max_steps/tokens/wall_clock); graceful failure with partial trace.
- **Evaluability:** every manifest version has a dev+held-out eval report; deterministic eval mode.
- **Observability:** full structured trace per run; token/cost accounting.
- **Accessibility:** 3D graph has 2D fallback, reduced-motion, keyboard nav.

## 13. Tech Stack

- **Frontend:** Next.js, React, TypeScript, Three.js (react-three-fiber), Tailwind.
- **Backend:** Python, FastAPI, Pydantic, SSE.
- **Agents:** LangGraph (+ LangChain where useful), Unified Agent Core.
- **Sandbox:** E2B (managed) or Docker/Firecracker (self-host) behind `CodeExecutor` interface.
- **Memory:** mem0 + LangGraph checkpointer (Postgres/SQLite).
- **Data:** Postgres; pgvector/Qdrant for code/doc embeddings.
- **MCP:** MCP client (stdio/HTTP) → `BaseTool` adapter.
- **Eval/Testing:** pytest; eval harness in `agent-core`; optional promptfoo/langsmith-style reporting (self-built minimal is fine for v1).
- **Infra:** Docker Compose local; env-based secrets.

## 14. Evaluation & Testing Strategy (Authoritative)

> AgentForge has **three** distinct correctness surfaces, each with its own discipline: (1) **agent quality** via an eval harness with split discipline, (2) **sandbox safety** via a security test matrix, (3) **system correctness** via the software test pyramid. Because there is no model training, "validation/testing" here means **dev/held-out evaluation of agents**, not gradient training.

### 14.1 Agent evaluation — dev / held-out split (the train/val/test analog)
- Each **EvalSuite** is a set of tasks: `{input, expected_outcome | rubric, scoring_mode}`.
- Tasks are split into **dev** and **held-out** partitions (disjoint), analogous to val/test:
  - **Dev set** — used while iterating prompts, tools, routing, manifests. You may look at it freely.
  - **Held-out set** — used only to *report* quality and to gate promotion. **Not inspected during iteration** (prevents "prompt overfitting" — the LLM analog of test leakage).
- **Leakage rule:** dev examples must not appear (verbatim or near-duplicate) in held-out; a check enforces disjointness.
- Report **dev and held-out pass rates side by side**; a large dev≫held-out gap signals overfitting to dev examples.

### 14.2 Scoring modes (and their caveats)
- **Programmatic/exact:** deterministic checks (e.g., sandbox returned 42, JSON matches schema). Preferred where possible.
- **Rubric checks:** boolean assertions (cited a source? stayed in scope? called the right tool?).
- **LLM-as-judge:** for open-ended quality; **caveats enforced** — fixed judge prompt + model, temperature 0, and **periodic human spot-check** to detect judge drift/bias. Judge is never the same call being judged.

### 14.3 Determinism & regression gating
- Eval runs use **eval mode** (temp=0, fixed seeds where supported, memory isolated) → stable pass/fail; measure **flake rate**, target < 5%.
- **Regression gate (Epic H5):** any manifest/prompt edit re-runs the suite; if held-out pass rate drops beyond tolerance vs the current promoted version, the new version is **blocked** and the diff surfaced. Dev-only gains that don't reproduce on held-out are flagged.

### 14.4 Sandbox security test matrix (build-blocking)
Each is an automated test that must be **contained**:
| Attack | Expected result |
|---|---|
| Read host filesystem (`/etc/passwd`, project files) | Denied / not present |
| Outbound network call | Blocked (egress off by default) |
| Fork bomb / process explosion | Killed by process/limit caps |
| Memory bomb | Killed at memory cap |
| Infinite loop | Killed at wall-clock timeout |
| Non-allowlisted package import | Rejected |
| Secret in code/env echoed to logs | Redacted in captured output |
These run in CI; a single failure blocks release (PRD §12 security).

### 14.5 Software test pyramid (system correctness)
- **Unit:** manifest validator (unknown-ref → error), registry `register/get/list`, tool arg-schema validation, calibration/scoring helpers, trace serialization.
- **Contract:** every registry implementation satisfies its interface (`MemoryProvider`, `ModelProvider`, `CodeExecutor`, `MCPConnector`) — parametric conformance tests so a new backend must pass the same suite.
- **Integration:** runtime + LangGraph + a real tool + checkpointer end-to-end; MCP discover→adapt→invoke; mem0 add/search/delete.
- **E2E:** author a manifest in the UI → run → stream trace → replay in 3D (Playwright).
- **Load:** concurrent runs; sandbox p95 budget; trace-stream latency.

### 14.6 Extension conformance test (the "no redesign" guarantee)
An automated test adds a new tool + a new agent manifest + a new memory backend **from outside the core package** and asserts they work with **zero diffs to `packages/agent-core`**. This operationalizes PRD §8.5 and §5's extensibility metric.

### 14.7 CI gates
`lint → unit → contract → sandbox-security-matrix → integration → extension-conformance → e2e (smoke)`; full agent-eval suites run on manifest changes and nightly (LLM calls are cost-metered, so not every commit).

## 15. Sandbox Detail

- **Isolation:** container/microVM per job; no host mounts; egress disabled by default (opt-in allowlist per agent).
- **Limits:** CPU shares, memory cap, wall-clock timeout, output size cap, max processes.
- **Interface:** `CodeExecutor.run(code, ctx)` → `ExecResult{stdout, stderr, return, artifacts, exit_code, timed_out}`.
- **As a tool:** `CodeExecutorTool` wraps it so a "coder" agent can invoke it; results feed back into the graph.
- **Safety:** the §14.4 matrix is the acceptance contract.

## 16. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Sandbox escape / abuse | Deny-by-default isolation, limits, allowlist, CI escape-test matrix (§14.4), single-tenant v1 |
| Prompt overfitting (looks good, isn't) | Dev/held-out split + regression gate (§14.1, §14.3) |
| LLM-as-judge bias | Fixed judge config + human spot-check (§14.2) |
| Over-engineered core (YAGNI) | Only the registries/interfaces actually needed; add a new interface when a 2nd impl appears |
| LangGraph API churn | Pin versions; thin adapter localizes upgrades |
| MCP variability | Adapter normalizes to `BaseTool`; validate discovered schemas |
| 3D graph complexity for big runs | Cap visible nodes, cluster, timeline replay |
| Secret leakage via traces/logs | Redaction layer; secrets from env/vault at runtime, never persisted |
| Eval cost blowup | Metered LLM eval; nightly + on-change, not per-commit |

## 17. Skills-Coverage Matrix

| Skill you wanted | Where it lives in AgentForge |
|---|---|
| Multi-agent + skills (extensible) | Epic A/B + Unified Agent Core §8 |
| Robust/unified harness, extend without redesign | §8.1–8.6 + extension-conformance test §14.6 |
| Prompts | PromptRegistry, `prompt_ref` |
| Memory (mem0) | Epic D + §8.3 MemoryProvider |
| Sandbox for running code | Epic C + §15 + security matrix §14.4 |
| MCP connections | Epic E + §8.3 MCPConnector |
| Web search tool | Built-in WebSearchTool (Epic E) |
| Tools (unified) | `BaseTool` + ToolRegistry |
| **Training / validating / testing (LLM analog)** | **Epic H + §14 (dev/held-out eval, determinism, regression gate) + software pyramid** |
| Three.js 3D rendering | Epic F (live execution graph) |
| Image/code embedding search | EmbeddingSearchTool (shared skill w/ FloraLens) |

## 18. Open Questions — RESOLVED (2026-07-06)

All v1 decisions locked; documented here as rationale. Reopen only with new evidence.

1. **Sandbox backend → E2B for v1** (fastest path to safe isolation). Docker/Firecracker impl kept behind the same `CodeExecutor` interface as the self-host fallback.
2. **Manifest authoring → YAML-first + live validation.** Visual builder deferred (YAGNI).
3. **Model providers → Anthropic only (claude-sonnet-5)** behind `ModelProvider`; OpenAI/local drop in later with no core change.
4. **User-defined tools → code-only registration for v1.** DB-persisted user tools add a security + eval surface; deferred.
5. **Eval harness → minimal in-house.** The harness is the learning goal; keeps determinism + dev/held-out split under our control. Export to LangSmith later if desired.
6. **Trace/eval retention → full traces in Postgres with an N-day + size cap, plus step-sampling for runs beyond a step threshold.** Exact N/threshold tuned in Phase 8.

Remaining true unknowns (resolve during build, non-blocking): web-search provider (Tavily vs Brave vs SerpAPI) — pick by cost/quota in Phase 3; sandbox egress-allowlist UX — decide when a real tool needs network.

> See `./IMPLEMENTATION-PLAN.md` for the phased build roadmap.
