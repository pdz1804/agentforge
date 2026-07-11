# AgentForge Roadmap

A horizon-based roadmap for AgentForge and the shared `agent_core` runtime (published to PyPI as
**`pdz-agent-core`**). Organized as **Now / Next / Later**. Shared-platform items also appear in the
[FloraLens roadmap](../../floralens/docs/roadmap.md); the full planning detail lives in
[`plans/260711-1707-superior-improvements-roadmap`](../../plans/260711-1707-superior-improvements-roadmap/plan.md).

**Effort key:** S = small · M = medium · L = large.

## Principles

- **Behavior-frozen:** existing `data-testid`s, the SSE event contract, the 3D graph, and the theme
  toggle are preserved. New UI is additive.
- **`agent_core` change ⇒ tagged release:** any public-surface change ships as a new `pdz-agent-core`
  version with notes and a semver-correct bump.
- **Docs follow reality:** docs are corrected to match code; claims are not aspirational.
- **CI stays green; secrets never committed.**

---

## Now — finish what the docs promise

Wire every advertised capability to its existing endpoint and correct doc over-claims. Near-zero
architectural risk.

**UI-testability (over already-existing APIs):**

- **Memory inspector panel** (M) — view/add/clear over `GET/POST/DELETE /api/memory`.
  *Done when:* write a memory, see it listed, delete it — all from the UI.
- **Embedding index panel** (S) — "Index a document" form → `POST /api/index`.
  *Done when:* index a doc, then a run's `embedding_search` returns it. (Needs `OPENAI_API_KEY`.)
- **Sandbox direct-exec panel** (S) — code box → `POST /api/sandbox/exec`.
  *Done when:* `print(2+2)` shows `4` with stdout/stderr/exit.
- **Manifest versioning / diff UI** (M) — save/load + version list + diff over `/api/agents*`.
  *Done when:* save two versions and view the diff in the UI.
- **Run-history clickable + trace export** (M) — rows reopen the stored trace; export button →
  `GET /api/runs/{id}/export`.
  *Done when:* click a past run → its trace reopens; export downloads JSON.

**Doc-truth reconciliation (docs only):**

- **Guardrails scope** (S) — architecture doc says guardrails "inspect every tool call before
  execution"; the code inspects only the final answer (`guardrails.py:52`). Correct the doc to
  "final-answer guardrails"; note the pre-tool-call hook as a Next item.
- **Timeout guardrail** (S) — the `timeout_30s` guardrail isn't registered; timeout is
  `limits.wall_clock_s`. Correct the doc (or add a real guardrail in Next).
- **`/api/mcp` documented** (S) — the endpoint exists (`main.py:162`); add it to `docs/api.md`.
- **Auth codes** (S) — missing key returns **401** (docs say 403); document the `X-API-Key` header.

**Release hygiene:**

- **`pdz-agent-core` CHANGELOG + semver policy** (M) — backfill 0.1.0→0.1.2 and state the public API +
  semver discipline. Unblocks the Next-phase 0.1.3 release and FloraLens consuming the package.

---

## Next — integrations, platform, core UX

**Integrations:**

- **MCP HTTP/SSE (Streamable) connector + auth** (L) — today only `StdioMCPConnector` exists
  (`mcp/connector.py:73`), so remote/hosted public MCP servers and bearer/header auth are unreachable.
  Add an HTTP/SSE connector with an `Authorization`/headers config field. **Release as
  `pdz-agent-core` 0.1.3.**
  *Done when:* bind a remote public MCP server over HTTP and call a tool; a bearer-auth server succeeds
  with a token and 401s without.
- **More model providers** (M each) — Google Gemini, Ollama/local, AWS Bedrock via the existing
  `ModelProvider` extension point. No core-contract change.
- **OpenTelemetry trace export + cost dashboard** (M) — bridge the `TraceEvent` bus to OTLP; persist
  token/cost per run; a dashboard reads persisted cost. Trace/cost persistence becomes default.

**Platform hardening:**

- **Real auth** (L) — email/password + OAuth + a web login surface. The shipped JWT is dev-only scaffold
  (the token minter is **not** login). Per-user namespaces for runs, evals, manifests, memories. The
  optional API-key path stays for service auth.
- **Observability** (M) — structured logging, metrics, error tracking.
- **Persistence default-eligible** (L) — Postgres run/eval/manifest stores + migrations, feature-detected
  by `DATABASE_URL`; **pgvector** a default-eligible vector backend; a **shared vector service** across
  both apps (one interface replacing AF in-memory + FL cosine index).
- **CI/CD depth** (M each) — mypy advisory→blocking; coverage thresholds; promote advisory
  pip-audit/bandit to blocking once clean; container images + a deploy target.
- **Pre-tool-call guardrail hook** (M) — inspect/deny/redact tool inputs *before* execution; makes the
  (now corrected) architecture claim real. Additive to the existing final-answer guardrails.

**Core product UX:**

- **Visual (non-YAML) manifest builder** (L) — drag-drop builder over the YAML editor.
- **Run comparison** (M) — compare two runs side-by-side.
- **Agent-template gallery** (M) — browse/instantiate templates (beyond the 9 capability templates).
- **Per-agent cost aggregation** (M) — cost breakdown for multi-agent supervisor runs.

---

## Later — scale, alternative backends, research

- **Qdrant vector backend** (L) — a third backend behind the shared vector interface (beyond in-memory +
  pgvector); env-selected, optional.
- **E2B sandbox backend** (L) — alternative to Docker `CodeExecutor`; same protocol, env-selected; must
  pass the same 8-test security matrix. Docker stays default.
- **`pdz-agent-core` docs site + typed public API** (M-L) — a published docs site and type-checked public
  exports, replacing the "docs live in the repo" pointer.
- **Research bets** (L each, gate-first) — eval-driven-development loop (auto-iterate prompts against the
  dev suite, gate on held-out); auto-repair agents; cost-optimal model routing (uses cost persistence,
  gate: cost↓ at equal pass-rate); richer multi-agent orchestration patterns.

---

## Sequencing

1. Now doc reconciliation first (cheap, no code risk) → UI-testability wiring → release hygiene.
2. MCP HTTP/SSE is releasable independently (0.1.3) and unblocks FloraLens's PyPI migration.
3. Real auth + persistence precede per-user features and dashboards.
4. Later backends and research bets follow the shared vector service and cost persistence.

## Open questions

- Real-auth identity provider (home-grown vs. Auth.js/Clerk/Supabase) — product decision needed.
- Deploy/hosting target for container images — unspecified.
