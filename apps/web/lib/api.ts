// Thin client for the AgentForge backend. Same-origin (Next rewrites proxy to
// the FastAPI), so paths are relative.

export type TraceEvent = {
  step?: number;
  type: "run_started" | "model" | "tool" | "answer" | "limit" | "error" | "done";
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
  const r = await fetch("/health", { cache: "no-store" });
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}

export async function validateManifest(
  manifest: unknown,
): Promise<{ ok: boolean; id?: string; error?: string }> {
  const r = await fetch("/api/agents/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ manifest }),
  });
  return r.json();
}

export async function listRuns(limit = 20): Promise<RunSummary[]> {
  const r = await fetch(`/api/runs?limit=${limit}`, { cache: "no-store" });
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
    headers: { "Content-Type": "application/json" },
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
