# Implementation Plan — AgentForge

Phased roadmap for `PRD.md` (v1.1). AgentForge is the flagship home of the **Unified Agent Core**
(`packages/agent-core`), which FloraLens also consumes — so **build the core here first**.
Stack: FastAPI + LangGraph + mem0 + sandbox (Python) / Next.js + Three.js (TS).
**The evaluation & testing strategy in PRD §14 is binding on Phases 4, 8, 9, and 10.**

**Status legend:** ☐ pending · ◐ in-progress · ☑ done

## Progress
- **2026-07-06** — Phase 1 complete; Phase 0 backend slice complete (Next.js `apps/web` deferred by scope decision). Delivered `packages/agent-core` (schema, registries, interfaces, loader/resolver, Echo tool + Echo/Anthropic model providers), `apps/api` (FastAPI `/health`, `/api/tools`, `/api/agents/validate`), `infra/docker-compose.yml` (Postgres). Verified: ruff clean; **20 tests pass** (16 core + 4 API). Phase 1 exit contract proven (valid manifest resolves; unknown ref → clear aggregated error). Deferred-and-documented in `loader.py`: `sub_agents`/`guardrails`/`io_schema` resolution (Phases 2/6).

## Phase Overview

| # | Phase | Depends on | Primary skill | Status |
|---|---|---|---|---|
| 0 | Foundation & scaffolding | — | Project setup | ◐ (backend done; web deferred) |
| 1 | Unified Agent Core — interfaces & registries | 0 | Harness architecture | ☑ |
| 2 | LangGraph runtime + single-agent run | 1 | Multi-agent orchestration | ☐ |
| 3 | Built-in tools + web search + MCP connector | 1,2 | Tools, MCP | ☐ |
| 4 | Code sandbox + security test matrix | 1 | **Secure sandbox + safety testing** | ☐ |
| 5 | Memory (mem0 + checkpointer) | 1,2 | Memory | ☐ |
| 6 | Multi-agent supervisor + Agent Builder UI | 2,3,5 | Orchestration, frontend | ☐ |
| 7 | Live 3D execution graph | 2,6 | Three.js | ☐ |
| 8 | Traces, observability, cost accounting | 2 | Observability | ☐ |
| 9 | **Agent evaluation harness (dev/held-out)** | 2,3,5 | **Validation/testing of agents** | ☐ |
| 10 | Software test pyramid + CI gates | 1–5,9 | **System correctness (PRD §14.5–14.7)** | ☐ |
| 11 | Auth, hardening, secret redaction | all | Platform, security | ☐ |
| 12 | Cross-product reuse check (FloraLens) | 1–5 | Integration proof | ☐ |

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
