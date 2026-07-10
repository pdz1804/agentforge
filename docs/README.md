# AgentForge Documentation

Welcome to the AgentForge documentation. Start here to understand the system, build agents, evaluate them, and extend the core.

## Quick Navigation

### For New Users
- **[Getting Started](../README.md#quickstart)** — Set up the API and web UI in 5 minutes
- **[Architecture Overview](./architecture.md)** — System design and how components interact
- **[Your First Agent](./architecture.md#agent-manifest-and-runtime)** — Build and run a simple agent

### For Developers
- **[API Reference](./api.md)** — Complete endpoint documentation with request/response examples
- **[Extending the Core](../README.md#extending-the-core-no-core-edits)** — Add tools, models, memory backends, and guardrails without core edits
- **[Architecture Deep Dive](./architecture.md)** — Detailed module structure, data flows, and technical decisions

### For Platform Builders
- **[Cross-Product Reuse](./cross-product-reuse.md)** — How FloraLens consumes the unmodified core
- **[Evaluation Harness](./architecture.md#evaluation-harness-dev--held-out-split)** — Build, run, and gate manifests on test suites
- **[Manifest Versioning](./api.md#agent-manifest-crud--versioning)** — Store, track, and diff agent versions

### For Product & Design
- **[Product Requirements (PRD)](../PRD.md)** — Vision, goals, functional requirements, and success metrics
- **[Implementation Plan](../IMPLEMENTATION-PLAN.md)** — Phased roadmap showing what shipped and when

---

## Documentation Files

| File | Purpose | Audience |
|---|---|---|
| [architecture.md](./architecture.md) | System design, module structure, runtime flow, agent manifest, eval harness, data models | Everyone |
| [api.md](./api.md) | HTTP API endpoints, request/response formats, authentication | Backend integrators, frontend devs |
| [cross-product-reuse.md](./cross-product-reuse.md) | How FloraLens uses the unmodified core, manifest example | Platform builders, product leads |
| [../PRD.md](../PRD.md) | Product vision, goals, functional specs, tech stack, testing strategy | Product managers, architects |
| [../IMPLEMENTATION-PLAN.md](../IMPLEMENTATION-PLAN.md) | Phase-by-phase roadmap, what shipped (v1.0) | Team leads, reviewers |

---

## Common Tasks

### Build Your First Agent

1. Read [Architecture: Agent Manifest](./architecture.md#agent-manifest-and-runtime)
2. Start the API: `python -m uvicorn app.main:app --port 8077 --app-dir apps/api`
3. Start the web UI: `cd apps/web && npm run dev`
4. Visit http://localhost:3000 and paste a manifest into the editor
5. Click Run and watch the 3D graph execute

### Add a Custom Tool

1. See [Extending the Core](../README.md#extending-the-core-no-core-edits) for a working example
2. Implement `BaseTool` with name, description, args_schema, and async `run()` method
3. Register it: `registries.tools.register("my_tool", MyTool())`
4. Reference it in a manifest: `tools: [my_tool, web_search]`

### Run an Eval Suite

1. Read [Architecture: Evaluation Harness](./architecture.md#evaluation-harness-dev--held-out-split)
2. Prepare dev + held-out task suites (see `suites/` for format)
3. POST to `/api/eval` with your manifest and suite IDs
4. Review the dev vs held-out report; promote a baseline if the held-out set passes

### Deploy with Postgres

1. Set `DATABASE_URL` in `.env`
2. Start Postgres: `docker compose -f infra/docker-compose.yml up -d`
3. The API auto-connects and persists runs, traces, and eval reports

---

## Key Concepts

### Agent Manifest
A declarative YAML/JSON document fully specifying an agent: model config, tools, prompts, memory, limits, evaluation suite. See [architecture.md](./architecture.md#agent-manifest-and-runtime).

### Unified Core
The `packages/agent-core` Python package: schema, registries, LangGraph runtime, eval harness, built-in tools. Shared between AgentForge and FloraLens — extensible without redesign.

### Dev / Held-Out Split
Agent evaluation discipline (LLM analog of train/val/test): iterate prompts on the dev set, report quality on a held-out set never seen during development. Regression gate blocks manifest versions that regress on held-out.

### Sandbox
Docker-isolated code execution with deny-by-default security: no host FS/network unless explicitly enabled, CPU/memory/time limits, package allowlist, secret redaction.

### Server-Sent Events (SSE)
`POST /api/runs` streams trace events in real-time as the agent executes. Frontend receives `run_started`, `step`, `tool_call`, `tool_result`, `answer`, `limit`, and error events.

### Eval Harness
`POST /api/eval` runs a manifest against dev + held-out task suites with deterministic scoring (programmatic, rubric, or LLM-as-judge). Returns a `DevHeldOutReport` with side-by-side pass rates and regression detection.

---

## Directory Structure

```
.
├── README.md                      # This file
├── architecture.md                # System design, module structure, flow diagrams
├── api.md                         # HTTP API reference
├── cross-product-reuse.md         # FloraLens integration example
├── assets/
│   ├── builder.png               # Agent Builder screenshot
│   ├── eval.png                  # Eval panel screenshot
│   └── about.png                 # About page screenshot
├── ../packages/agent-core/        # Shared core (manifest, registries, runtime)
├── ../apps/api/                   # FastAPI backend
├── ../apps/web/                   # Next.js frontend
├── ../infra/docker-compose.yml    # Docker Postgres + full stack
└── ../suites/                     # Eval task suite examples
```

---

## FAQ

**Q: Can I use AgentForge without Docker?**
A: Yes. The web UI and API run fine without Docker. The sandbox (`/api/sandbox/exec`) requires Docker, but agents can still use other tools (web_search, embedding_search, etc.).

**Q: How do I add a model provider (e.g., Llama, Mistral)?**
A: Implement `ModelProvider` and register it. No core edits. See the Anthropic provider in `packages/agent-core/src/agent_core/models/anthropic.py` as a template.

**Q: Do I need Postgres?**
A: No. The default in-memory stores work for demos. Set `DATABASE_URL` to persist runs, traces, eval reports, and manifest versions to Postgres.

**Q: How is AgentForge different from LangChain?**
A: AgentForge is a full workbench (UI + eval + sandbox + observability) for building, running, and evaluating multi-agent systems. It uses LangGraph (LangChain's orchestration library) under the hood but adds eval discipline (dev/held-out split, regression gating), safe sandboxing, and a unified manifest schema that makes extension plug-and-play without code edits.

**Q: Is there per-user isolation?**
A: Phase 11 is partial. Opt-in shared-key auth (`AGENTFORGE_API_KEY`) and rate limiting are in place, but there is no per-user isolation yet. All runs and memories are shared across callers. Future versions will add per-user namespacing.

**Q: Can FloraLens run on the same core unmodified?**
A: Yes. FloraLens consumes `packages/agent-core` directly (editable install) with zero core changes. See [cross-product-reuse.md](./cross-product-reuse.md).

---

## Support & Contribution

- **Questions?** See [PRD.md](../PRD.md) for the product vision and [IMPLEMENTATION-PLAN.md](../IMPLEMENTATION-PLAN.md) for the phased roadmap.
- **Found a bug?** Check the GitHub issues and create a detailed report.
- **Want to extend?** Follow the patterns in [../README.md#extending-the-core-no-core-edits](../README.md#extending-the-core-no-core-edits).

---

*Last updated: 2026-07-10*
