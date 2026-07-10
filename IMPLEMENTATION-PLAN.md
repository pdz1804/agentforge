# Implementation Plan — AgentForge

Phased roadmap for `PRD.md` (v1.1). AgentForge is the flagship home of the **Unified Agent Core**
(`packages/agent-core`), which FloraLens also consumes — so **build the core here first**.
Stack: FastAPI + LangGraph + mem0 + sandbox (Python) / Next.js + Three.js (TS).
**The evaluation & testing strategy in PRD §14 is binding on Phases 4, 8, 9, and 10.**

**Status legend:** ☐ pending · ◐ in-progress · ☑ done

## Progress
- **2026-07-10 (Phases 7, 9, 10 complete; 11 partial; 12 proven)** — Eval harness shipped: `eval.py`
  + `POST /api/eval` + `eval-panel.tsx` (dev/held-out split with disjointness check, programmatic/rubric/LLM-judge
  scoring, deterministic eval mode, regression gate). CI shipped (`.github/workflows/ci.yml`: lint → python tests →
  sandbox-security matrix → web build) with `test_conformance.py` + `test_extension_conformance.py`. Phase 7 3D graph
  timeline scrubber + reduced-motion fallback shipped. Phase 8 durable `PostgresRunStore` + retention/prune shipped.
  Phase 11 hardening: opt-in shared-key auth (`AGENTFORGE_API_KEY`), rate limiting, secret redaction in traces/logs —
  **partial: single shared key, no per-user isolation**. Phase 12: FloraLens naturalist assistant runs on unmodified
  `agent_core` (US-6 met).
- **2026-07-10 (Phase 0 web UI + Phase 7)** — Agent Builder web UI shipped (Next.js 14, port 3000).
  Features: YAML manifest editor + template gallery, live SSE run panel (stream + trace), run history, dark/light theme toggle,
  Builder/About tabs, intro page. **3D Execution Graph** (Phase 7): TraceGraph3D.tsx (Three.js, agent + tool nodes, 
  pulsing on activation, edge highlighting, timeline scrubber). Single-origin proxy to API (:8077). 
  Playwright e2e tests.
- **2026-07-06 (Phase 8, observability)** — Run persistence + token/cost. `RunRecord` (status, answer, full trace, usage, cost) + `RunStore` (`InMemoryRunStore` default, newest-first, bounded). `POST /api/runs` streams `run_started` event, accumulates trace, **persists on every exit path** (compile-fail, run-fail, timeout, success, client-disconnect via `finally`, idempotent). Token usage from trace events; `token_cost` from price table. `GET /api/runs` (summaries), `GET /api/runs/{id}`, `GET /api/runs/{id}/export`. **76 tests** (68 offline + 8 docker), ruff clean. **Deferred:** trace-viewer UI, Postgres store, trace-size limits.
- **2026-07-06 (Phase 6, multi-agent + UI deferred then shipped)** — Agents-as-tools: `compile_agent` recursively compiles supervisor's `sub_agents`, exposes as `ask_<id>` tools. Cycle detection + tool-name collision guard. `eval_mode` propagates via contextvar (deterministic + memory-isolated). **69 tests**, ruff clean. **Then Phase 0 web:** Next.js Agent Builder UI shipped later (full feature set above).
- **2026-07-06 (Phase 5, long-term memory)** — `MemoryProvider`: `InMemoryMemoryProvider` (default) + `Mem0MemoryProvider` (semantic). On run: retrieve relevant memories, inject as system context, persist after answering. **Eval-mode isolated** (no retrieve/persist). Memory API: `GET/POST/DELETE /api/memory`. **57 tests**, ruff clean. **Deferred:** durable SQLite checkpointer (Phase 5b); mem0 live smoke.
- **2026-07-06 (Phase 4)** — Docker code sandbox. `DockerCodeExecutor`: deny-by-default (no host mounts, `--network none`, non-root, caps dropped). **Security matrix PASSED**: 8 rows (network, host-FS, fork, memory, infinite-loop, non-root, stdout cap, import deny). **50 tests**, ruff clean. **Deferred:** E2B backend.
- **2026-07-06 (Phase 3, partial)** — Multi-provider LLM + web search. `OpenAIModelProvider` + `AnthropicModelProvider` (both tool-use). `WebSearchTool` (Tavily). `apps/api/Dockerfile` + Compose. **Live Docker smoke PASSED**. **37 tests**. **Deferred:** EmbeddingSearchTool+pgvector, MCP connector live.
- **2026-07-06 (Phase 2)** — LangGraph runtime. `compile_agent` → `StateGraph` (agent↔tools ReAct). `TraceEvent` bus. `arun` + `astream`. Limits enforced (max_steps, wall_clock_s). **27 tests**, ruff clean.
- **2026-07-06 (Phase 0-1)** — Phase 1 complete; Phase 0 backend slice. `packages/agent-core` (schema, registries, interfaces, Echo/Anthropic providers), `apps/api` (FastAPI), `infra/docker-compose.yml`. Phase 1 exit proven. Committed `f38faac`.

## Phase Overview

| # | Phase | Depends on | Primary skill | Status |
|---|---|---|---|---|
| 0 | Foundation & scaffolding | — | Project setup | ☑ (backend + web shipped) |
| 1 | Unified Agent Core — interfaces & registries | 0 | Harness architecture | ☑ |
| 2 | LangGraph runtime + single-agent run | 1 | Multi-agent orchestration | ☑ |
| 3 | Built-in tools + web search + MCP connector | 1,2 | Tools, MCP | ☑ |
| 4 | Code sandbox + security test matrix | 1 | **Secure sandbox + safety testing** | ☑ |
| 5 | Memory (mem0 + checkpointer) | 1,2 | Memory | ☑ (long-term memory + durable SQLite thread checkpointer shipped) |
| 6 | Multi-agent supervisor + Agent Builder UI | 2,3,5 | Orchestration, frontend | ☑ (supervisor + full web UI shipped) |
| 7 | Live 3D execution graph | 2,6 | Three.js | ☑ (TraceGraph3D.tsx; timeline scrubber + reduced-motion fallback shipped) |
| 8 | Traces, observability, cost accounting | 2 | Observability | ☑ (persistence, cost, API; Postgres store + retention shipped) |
| 9 | **Agent evaluation harness (dev/held-out)** | 2,3,5 | **Validation/testing of agents** | ☑ (eval.py + `/api/eval` + eval-panel.tsx; dev/held-out split, scoring modes, regression gate) |
| 10 | Software test pyramid + CI gates | 1–5,9 | **System correctness (PRD §14.5–14.7)** | ☑ (CI workflow + conformance/extension-conformance tests + sandbox-security gate) |
| 11 | Auth, hardening, secret redaction | all | Platform, security | ◐ (shared-key auth + rate limits + trace/log redaction shipped; no per-user isolation yet) |
| 12 | Cross-product reuse check (FloraLens) | 1–5 | Integration proof | ☑ (FloraLens naturalist assistant runs on unmodified `agent_core`) |

---

## Phase 0 — Foundation & Scaffolding
**Deliver:** monorepo skeleton + local infra.
- Layout: `apps/web`, `apps/api`, `packages/agent-core` (shared, installable), `suites/` (eval tasks), `infra/` (docker-compose: Postgres, sandbox runtime).
- Env config; no secrets committed; health handshake.
**Exit:** `docker compose up` runs; web ↔ api health OK; `agent-core` importable.

## Phase 1 — Unified Agent Core: Interfaces & Registries
**Deliver:** the harness skeleton (PRD §8) — the most important phase.
- Pydantic **Manifest** schema (incl. `eval_suite`, `limits`) + loader/validator (fail-fast on unknown refs).
- Interfaces: `BaseTool`, `MemoryProvider`, `ModelProvider`, `MCPConnector`, `CodeExecutor`, `Registry`.
- Registries: Tool/Prompt/MCP/Memory/Model with shared `register/get/list`.
- ModelProvider: Anthropic impl (`claude-sonnet-5`); **eval-mode override** (temp=0) plumbed.
- Trivial `EchoTool` + one prompt to prove wiring.
**Exit:** load a manifest referencing EchoTool → validates; unknown ref → clear error.

## Phase 2 — LangGraph Runtime + Single-Agent Run
**Deliver:** manifest → running agent.
- Compiler: Manifest → LangGraph `StateGraph` (typed state) + checkpointer (SQLite/Postgres).
- Single agent loop: model call → optional tool call → answer, honoring `limits`.
- Trace bus emits step events; `POST /api/runs` (SSE) streams output + trace.
- **Eval-mode run path** (deterministic) exposed for Phase 9.
**Exit:** run a one-agent manifest via API; tool call executes; trace streamed; limits enforced.

## Phase 3 — Built-in Tools + Web Search + MCP Connector
**Deliver:** real tools + external tool integration.
- Tools: `WebSearchTool`, `HttpFetchTool`, `EmbeddingSearchTool` (pgvector, shared w/ FloraLens).
- MCP connector: configure server (stdio/HTTP) → discover → adapt to `BaseTool` → register.
- Per-agent tool allowlist enforced.
**Exit:** US-1 (add tool, no core edit) + US-5 (MCP tool callable) met.

## Phase 4 — Code Sandbox + Security Test Matrix
**Deliver:** safe code execution (PRD §15) with the safety matrix as the acceptance contract.
- `CodeExecutor` impl (E2B default; Docker option behind same interface): deny host FS/net, CPU/mem/time caps, output cap, package allowlist.
- `POST /api/sandbox/exec` + `CodeExecutorTool` wrapper for agents.
- **Security test matrix (PRD §14.4), build-blocking:** host-FS read, network egress, fork bomb, memory bomb, infinite loop, non-allowlisted import, secret redaction → all contained.
**Exit:** US-2 met; every matrix row passes in CI.

## Phase 5 — Memory (mem0 + Checkpointer)
**Deliver:** long- and short-term memory.
- `MemoryProvider` mem0 impl (namespaced user/agent/session); wire into runtime (read→augment, write→persist); **memory isolated in eval mode**.
- LangGraph checkpointer for thread state.
- Memory inspector API (view/search/edit/delete).
**Exit:** US-4 met; new session recalls prior facts; delete removes from retrieval.

## Phase 6 — Multi-Agent Supervisor + Agent Builder UI
**Deliver:** real multi-agent orchestration + authoring.
- Supervisor/router node; `sub_agents` composition; loop-until-answer with limits.
- Agent Builder UI: YAML editor + live validation, template gallery, run panel (streamed output + tool trace), manifest versioning/diff.
**Exit:** a supervisor with ≥2 sub-agents runs end-to-end; a new agent authored via UI (no code) runs.

## Phase 7 — Live 3D Execution Graph (Three.js)
**Deliver:** the visualization.
- react-three-fiber graph: nodes (supervisor/sub-agents/tools) + edges.
- Live: nodes animate on activation, edges pulse on tool/message; click node → I/O inspector.
- Timeline scrubber replays a run from trace; 2D + reduced-motion + no-WebGL fallbacks.
**Exit:** US-3 met; run reconstructable/replayable from trace.

## Phase 8 — Traces, Observability, Cost Accounting
**Deliver:** full run introspection.
- Persist `TraceEvent`; trace viewer (list + export JSON); token/cost per run and per agent.
- Retention/sampling policy for long runs (Open Q#6).
**Exit:** every run has a complete, exportable trace; cost visible.

## Phase 9 — Agent Evaluation Harness (dev / held-out)
**Deliver:** the "validation/testing" surface for agents (PRD §14.1–14.3) — the LLM analog of train/val/test.
- `EvalSuite` model + `suites/` task format: `{input, expected|rubric, scoring_mode}`.
- **Dev/held-out split** with disjointness (incl. near-duplicate) check; iterate on dev, report on held-out.
- Scoring modes: programmatic, rubric, **LLM-as-judge** (fixed judge prompt+model, temp=0, human spot-check hook).
- **Deterministic eval mode** (temp=0, isolated memory); measure flake rate (< 5%).
- `POST /api/eval/{manifest_id}` → dev+held-out `EvalReport`; UI report view (dev vs held-out side by side).
- **Regression gate:** manifest/prompt edit re-runs suite; held-out drop beyond tolerance blocks promotion + shows diff.
**Exit:** US-7 met; a quiet prompt regression is caught and blocked; dev-only gains flagged.

## Phase 10 — Software Test Pyramid + CI Gates
**Deliver:** system correctness (PRD §14.5–14.7).
- **Unit:** manifest validator, registries, tool arg-schema, trace serialization.
- **Contract:** parametric conformance suite every registry impl must pass (Memory/Model/CodeExecutor/MCP backends).
- **Integration:** runtime+LangGraph+tool+checkpointer; MCP discover→invoke; mem0 CRUD.
- **Extension-conformance test:** add tool+agent+memory backend from outside core → **zero core diffs** (PRD §14.6).
- **E2E:** author manifest → run → trace → 3D replay (Playwright). **Load:** concurrent runs, sandbox p95.
- CI: `lint → unit → contract → sandbox-security-matrix → integration → extension-conformance → e2e smoke`; agent-eval on manifest change + nightly.
**Exit:** all PRD §14.5–14.7 tests green; extension-conformance + security matrix actually block on violation.

## Phase 11 — Auth, Hardening, Secret Redaction
**Deliver:** demo-ready + safe.
- Auth + per-user isolation; rate limits; **secret redaction** in traces/logs; secrets from env/vault only.
- Error budgets; README + run docs.
**Exit:** all NFRs (§12) met; clean secret scan; redaction verified.

## Phase 12 — Cross-Product Reuse Check
**Deliver:** proof the core is truly reusable.
- Load FloraLens naturalist manifests against `packages/agent-core`; run `EmbeddingSearchTool` + `WebSearchTool`.
- Fix any leak that forced FloraLens-specific core edits (should be none).
**Exit:** US-6 met — FloraLens runs on unchanged core.

---

## Cross-Phase Guarantees
- **Sandbox safety:** Phase 4 exit gated on the CI security matrix; deny-by-default never relaxed.
- **Agent-eval honesty:** held-out set never inspected during iteration; regression gate enforced (Phase 9).
- **No-redesign extensibility:** proven by the extension-conformance test (Phase 10).
- **YAGNI on the core:** add a new interface only when a 2nd concrete impl actually appears.

## Suggested Build Order for Learning
0 → 1 → 2 (core + first run: biggest learning payoff) → 4 (sandbox + safety) → 3 (tools/MCP) → 5 (memory) → 9 (eval discipline early, so later changes are gated) → 6 (multi-agent + UI) → 7 (3D) → 8 → 10 → 11 → 12.

## Decisions (resolved — see PRD §18)
E2B sandbox (Docker behind same interface) · YAML-first authoring · Anthropic-only models · code-only tool registration · **minimal in-house eval harness** · full traces + N-day/size cap.
Non-blocking build-time picks: web-search provider (Tavily/Brave/SerpAPI) chosen in Phase 3; egress-allowlist UX when first needed.
