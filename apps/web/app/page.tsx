"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import yaml from "js-yaml";
import {
  getHealth,
  listRuns,
  runAgent,
  validateManifest,
  type Health,
  type RunSummary,
  type TraceEvent,
} from "@/lib/api";
import { TEMPLATES } from "@/lib/templates";
import TraceGraph3D from "./TraceGraph3D";

export default function Page() {
  const [health, setHealth] = useState<Health | null>(null);
  const [tpl, setTpl] = useState(TEMPLATES[0].key);
  const [manifestYaml, setManifestYaml] = useState(TEMPLATES[0].yaml);
  const [input, setInput] = useState(TEMPLATES[0].input);
  const [evalMode, setEvalMode] = useState(TEMPLATES[0].eval_mode);
  const [validity, setValidity] = useState<{ ok: boolean; msg: string } | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [answer, setAnswer] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const [cost, setCost] = useState<number | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const refreshRuns = useCallback(() => {
    listRuns(20).then(setRuns).catch(() => {});
  }, []);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    refreshRuns();
    // Abort any in-flight run stream if the page unmounts.
    return () => abortRef.current?.abort();
  }, [refreshRuns]);

  function loadTemplate(key: string) {
    const t = TEMPLATES.find((x) => x.key === key) ?? TEMPLATES[0];
    setTpl(key);
    setManifestYaml(t.yaml);
    setInput(t.input);
    setEvalMode(t.eval_mode);
    setValidity(null);
  }

  function parseManifest(): unknown {
    return yaml.load(manifestYaml);
  }

  async function onValidate() {
    setValidity(null);
    let manifest: unknown;
    try {
      manifest = parseManifest();
    } catch (e) {
      setValidity({ ok: false, msg: `YAML parse error: ${(e as Error).message}` });
      return;
    }
    try {
      const res = await validateManifest(manifest);
      setValidity(
        res.ok
          ? { ok: true, msg: `valid — id "${res.id}"` }
          : { ok: false, msg: res.error ?? "invalid" },
      );
    } catch (e) {
      setValidity({ ok: false, msg: (e as Error).message });
    }
  }

  async function onRun() {
    let manifest: unknown;
    try {
      manifest = parseManifest();
    } catch (e) {
      setRunError(`YAML parse error: ${(e as Error).message}`);
      setStatus("error");
      return;
    }
    setEvents([]);
    setAnswer(null);
    setRunError(null);
    setCost(null);
    setStatus("running");
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await runAgent(
        { manifest, input, eval_mode: evalMode },
        (ev) => {
          setEvents((prev) => [...prev, ev]);
          if (ev.type === "answer") setAnswer(ev.detail ?? "");
          if (ev.type === "error") {
            setRunError(ev.detail ?? "error");
            setStatus("error");
          }
          if (ev.type === "done") {
            setCost(ev.cost_usd ?? 0);
            setStatus((s) => (s === "error" ? s : "done"));
          }
        },
        ctrl.signal,
      );
      setStatus((s) => (s === "error" ? s : "done"));
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setRunError((e as Error).message);
        setStatus("error");
      }
    } finally {
      // Refresh history even on abort/error — the backend may have persisted it.
      abortRef.current = null;
      refreshRuns();
    }
  }

  function onStop() {
    abortRef.current?.abort();
    setStatus("idle");
  }

  const running = status === "running";

  return (
    <>
      <div className="topbar">
        <span className={`dot ${health ? "ok" : ""}`} data-testid="health-dot" />
        <h1>AgentForge — Agent Builder</h1>
        <span className="spacer" />
        <span className="meta" data-testid="health-meta">
          {health
            ? `core ${health.core_version} · models: ${health.models.join(", ")} · tools: ${health.tools.length}`
            : "backend offline"}
        </span>
      </div>

      <div className="layout">
        {/* LEFT: authoring */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <h2>Manifest</h2>
            <div className="body">
              <div className="row">
                <div>
                  <label htmlFor="tpl">Template</label>
                  <select
                    id="tpl"
                    data-testid="template-select"
                    value={tpl}
                    onChange={(e) => loadTemplate(e.target.value)}
                  >
                    {TEMPLATES.map((t) => (
                      <option key={t.key} value={t.key}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 6 }}>
                  <label htmlFor="evalmode" style={{ margin: 0 }}>
                    eval mode
                  </label>
                  <input
                    id="evalmode"
                    type="checkbox"
                    checked={evalMode}
                    onChange={(e) => setEvalMode(e.target.checked)}
                    style={{ width: 16, height: 16 }}
                  />
                </div>
              </div>

              <label htmlFor="manifest">YAML</label>
              <textarea
                id="manifest"
                data-testid="manifest-editor"
                value={manifestYaml}
                onChange={(e) => setManifestYaml(e.target.value)}
                spellCheck={false}
              />

              <label htmlFor="input" style={{ marginTop: 12 }}>
                Input
              </label>
              <input
                id="input"
                type="text"
                data-testid="run-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
              />

              <div className="row" style={{ marginTop: 12, marginBottom: 0 }}>
                <button className="secondary" data-testid="validate-btn" onClick={onValidate}>
                  Validate
                </button>
                {running ? (
                  <button data-testid="stop-btn" onClick={onStop}>
                    Stop
                  </button>
                ) : (
                  <button data-testid="run-btn" onClick={onRun}>
                    Run agent
                  </button>
                )}
              </div>
              {validity && (
                <p style={{ marginBottom: 0, marginTop: 10 }}>
                  <span className={`pill ${validity.ok ? "ok" : "bad"}`} data-testid="validity">
                    {validity.ok ? "VALID" : "INVALID"}
                  </span>{" "}
                  <span className="muted">{validity.msg}</span>
                </p>
              )}
            </div>
          </div>

          <div className="card">
            <h2>Run history</h2>
            <div className="body hist" style={{ padding: 0 }} data-testid="run-history">
              {runs.length === 0 && <p className="muted" style={{ padding: 14 }}>No runs yet.</p>}
              {runs.map((r) => (
                <div className="hist-row" key={r.id}>
                  <span className={`pill ${r.status === "completed" ? "ok" : r.status === "timeout" ? "warn" : "bad"}`}>
                    {r.status}
                  </span>
                  <span className="id">{r.id.slice(0, 8)}</span>
                  <span className="ans">{r.answer ?? "—"}</span>
                  <span className="cost">${r.cost_usd.toFixed(6)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT: run output + trace + 3D replay */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <h2>
              Run output{" "}
              <span
                className={`pill ${status === "done" ? "ok" : status === "error" ? "bad" : status === "running" ? "warn" : ""}`}
                data-testid="run-status"
              >
                {status}
              </span>
            </h2>
            <div className="body">
              {answer !== null && (
                <div className="answer" data-testid="answer">
                  <div className="lbl">Answer</div>
                  {answer}
                </div>
              )}
              {runError && (
                <p className="err" data-testid="run-error">
                  {runError}
                </p>
              )}
              {cost !== null && (
                <p className="muted mono" style={{ marginBottom: 0 }} data-testid="cost">
                  cost: ${cost.toFixed(6)}
                </p>
              )}
              {answer === null && !runError && status === "idle" && (
                <p className="muted" style={{ margin: 0 }}>
                  Author a manifest and click <b>Run agent</b> to stream the trace.
                </p>
              )}
            </div>
          </div>

          <div className="card">
            <h2>Trace</h2>
            <div className="body trace" data-testid="trace">
              {events.length === 0 && <p className="muted" style={{ margin: 0 }}>No events yet.</p>}
              {events.map((ev, i) => (
                <div className={`event ${ev.type}`} key={i} data-testid={`event-${ev.type}`}>
                  <div className="head">
                    {ev.step != null && <span className="step">step {ev.step}</span>}
                    <span className="node">{ev.node ?? ev.type}</span>
                    <span className="pill">{ev.type}</span>
                    {ev.usage && (ev.usage.input_tokens || ev.usage.output_tokens) ? (
                      <span className="usage">
                        {ev.usage.input_tokens ?? 0}→{ev.usage.output_tokens ?? 0} tok
                      </span>
                    ) : null}
                  </div>
                  {ev.detail && <div className="detail">{ev.detail}</div>}
                  {ev.tool_calls?.map((tc, j) => (
                    <div className="tc" key={j}>
                      ⚙ {tc.name}({JSON.stringify(tc.args)})
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h2>3D execution graph</h2>
            <div className="body" style={{ padding: 0 }} data-testid="trace-3d">
              <TraceGraph3D events={events} />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
