// Thin client for the AgentForge backend. Same-origin (Next rewrites proxy to
// the FastAPI), so paths are relative.

// Phase 11 hardening: when the API is deployed with AGENTFORGE_API_KEY set,
// the matching key must be exposed to the client build as
// NEXT_PUBLIC_AGENTFORGE_API_KEY so requests to protected endpoints carry it.
// Unset (the default/local-demo case) means no header is sent, matching the
// API's default-open behavior.
function authHeaders(): Record<string, string> {
  const key = process.env.NEXT_PUBLIC_AGENTFORGE_API_KEY;
  return key ? { "X-API-Key": key } : {};
}

export type TraceEvent = {
  step?: number;
  type: "run_started" | "model" | "tool" | "answer" | "limit" | "error" | "done" | "token";
  node?: string;
  detail?: string;
  tool_calls?: { name: string; args: Record<string, unknown>; id?: string }[];
  usage?: { input_tokens?: number; output_tokens?: number };
  run_id?: string;
  cost_usd?: number;
};

export type RunSummary = {
  id: string;
  manifest_id: string;
  model: string;
  status: string;
  cost_usd: number;
  created_at: string;
  answer: string | null;
};

export type Health = {
  status: string;
  core_version: string;
  tools: string[];
  models: string[];
};

export async function getHealth(): Promise<Health> {
  const r = await fetch("/health", { cache: "no-store", headers: authHeaders() });
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}

export async function validateManifest(
  manifest: unknown,
): Promise<{ ok: boolean; id?: string; error?: string }> {
  const r = await fetch("/api/agents/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ manifest }),
  });
  return r.json();
}

// ---- Eval harness (dev vs held-out suites) ----

export type EvalSuite = {
  suite_id: string;
  manifest_id: string;
  dev_task_count: number;
  held_out_task_count: number;
};

export type TaskScore = {
  task_id: string;
  score: number;
  passed: boolean;
  detail?: string;
  [k: string]: unknown;
};

export type SplitReport = {
  suite_id: string;
  manifest_id: string;
  split: string;
  task_scores: TaskScore[];
  pass_rate?: number;
  mean_score?: number;
};

export type DevHeldOutReport = {
  dev: SplitReport;
  held_out: SplitReport;
};

// Regression shape varies by backend config; keep it open and render defensively.
// The current backend (agent_core.eval.RegressionResult) reports `blocked`
// (true = a regression that blocks promotion); passed/ok/regressed are
// tolerated fallbacks for other builds.
export type RegressionVerdict = {
  blocked?: boolean;
  delta?: number; // held_out.pass_rate - baseline.pass_rate; negative = regression
  held_out_pass_rate?: number;
  baseline_pass_rate?: number;
  newly_failing_tasks?: string[];
  newly_passing_tasks?: string[];
  detail?: string;
  // Tolerated fallbacks for other/older backend builds.
  passed?: boolean;
  ok?: boolean;
  regressed?: boolean;
  [k: string]: unknown;
};

export type EvalResponse = {
  report_id?: string;
  report: DevHeldOutReport;
  regression?: RegressionVerdict | null;
};

// One llm_judge-scored task surfaced for human audit (backend SpotCheckSample).
export type SpotCheckSample = {
  task_id: string;
  suite_id?: string;
  split: string;
  input: string;
  answer?: string | null;
  judge_score: number;
  passed: boolean;
  judge_detail?: string;
  review_status?: string;
};

export type SpotCheckResponse = {
  report_id: string;
  manifest_id: string;
  samples: SpotCheckSample[];
};

export async function listSuites(): Promise<EvalSuite[]> {
  const r = await fetch("/api/suites", { cache: "no-store", headers: authHeaders() });
  if (!r.ok) throw new Error(`suites ${r.status}`);
  const j = await r.json();
  return j.suites ?? [];
}

// Surface FastAPI's {detail} when present, else a `<label> <status>` fallback.
async function apiError(r: Response, label: string): Promise<Error> {
  let msg = `${label}: ${r.status}`;
  try {
    const j = await r.json();
    if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* non-JSON error body */
  }
  return new Error(msg);
}

export async function runEval(body: {
  manifest: unknown;
  suite_id: string;
  agents?: unknown[];
  use_stored_baseline?: boolean;
}): Promise<EvalResponse> {
  const r = await fetch("/api/eval", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw await apiError(r, "eval failed");
  return r.json();
}

// Promote a stored report's held-out split to its manifest's baseline, so a
// later run can gate against it via `use_stored_baseline: true`.
export async function promoteBaseline(
  reportId: string,
): Promise<{ manifest_id: string; source_report_id: string; baseline_pass_rate: number }> {
  const r = await fetch(`/api/eval/${encodeURIComponent(reportId)}/promote`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!r.ok) throw await apiError(r, "promote failed");
  return r.json();
}

// Fetch a stored report's llm_judge samples queued for human audit. Reports
// with no llm_judge tasks return an empty `samples` list.
export async function getSpotCheck(reportId: string): Promise<SpotCheckResponse> {
  const r = await fetch(`/api/eval/${encodeURIComponent(reportId)}/spot-check`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!r.ok) throw await apiError(r, "spot-check failed");
  return r.json();
}

export async function listRuns(limit = 20): Promise<RunSummary[]> {
  const r = await fetch(`/api/runs?limit=${limit}`, { cache: "no-store", headers: authHeaders() });
  if (!r.ok) return [];
  const j = await r.json();
  return j.runs ?? [];
}

// Stream a run as Server-Sent Events, invoking onEvent per parsed event.
export async function runAgent(
  body: { manifest: unknown; input: string; eval_mode?: boolean; agents?: unknown[] },
  onEvent: (ev: TraceEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`run failed: ${r.status}`);

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const processFrame = (frame: string) => {
    // Concatenate every `data:` line in the frame (SSE multi-line data rule).
    const payload = frame
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).replace(/^ /, ""))
      .join("\n")
      .trim();
    if (!payload) return;
    try {
      onEvent(JSON.parse(payload) as TraceEvent);
    } catch {
      /* ignore malformed frame */
    }
  };

  const drainBuffer = () => {
    // Normalize CRLF so frame boundaries match regardless of proxy line endings.
    buffer = buffer.replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      processFrame(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 2);
    }
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    drainBuffer();
  }
  // Flush any multibyte tail + a final frame not terminated by a blank line.
  buffer += decoder.decode();
  drainBuffer();
  if (buffer.trim()) processFrame(buffer);
}
