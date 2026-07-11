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
import ThemeToggle from "./ThemeToggle";
import AboutPanel from "./AboutPanel";
import EvalPanel from "./eval-panel";
import {
  CheckIcon,
  DocIcon,
  GaugeIcon,
  GraphIcon,
  HistoryIcon,
  LayersIcon,
  LogoMark,
  OutputIcon,
  PlayIcon,
  StopIcon,
  ToolIcon,
  TraceIcon,
} from "./icons";

type Tab = "builder" | "eval" | "about";

export default function Page() {
  const [health, setHealth] = useState<Health | null>(null);
  const [tpl, setTpl] = useState(TEMPLATES[0].key);
  const [manifestYaml, setManifestYaml] = useState(TEMPLATES[0].yaml);
  const [input, setInput] = useState(TEMPLATES[0].input);
  const [evalMode, setEvalMode] = useState(TEMPLATES[0].eval_mode);
  // Child sub-agent manifest YAMLs for the selected template (supervisor
  // templates only). Empty for every other template, so onRun sends no
  // `agents` and behavior is unchanged.
  const [agentYamls, setAgentYamls] = useState<string[]>(TEMPLATES[0].agents ?? []);
  const [validity, setValidity] = useState<{ ok: boolean; msg: string } | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [answer, setAnswer] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "running" | "done" | "stopped" | "error">("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const [cost, setCost] = useState<number | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [tab, setTab] = useState<Tab>("builder");
  const abortRef = useRef<AbortController | null>(null);

  // Roving-focus keyboard support for the tablist (Left/Right/Home/End).
  function onTabKey(e: React.KeyboardEvent) {
    const order: Tab[] = ["builder", "eval", "about"];
    const i = order.indexOf(tab);
    let next: Tab | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = order[(i + 1) % order.length];
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = order[(i - 1 + order.length) % order.length];
    else if (e.key === "Home") next = order[0];
    else if (e.key === "End") next = order[order.length - 1];
    if (next) {
      e.preventDefault();
      setTab(next);
      document.getElementById(`tab-${next}`)?.focus();
    }
  }

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
    setAgentYamls(t.agents ?? []);
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
    let agents: unknown[] | undefined;
    try {
      manifest = parseManifest();
      // Supervisor templates carry child manifest YAMLs; parse each with the
      // same YAML loader as the main editor so the run endpoint's
      // `agents: [...]` gets real dicts (RunRequest.agents in app/main.py).
      agents = agentYamls.length ? agentYamls.map((y) => yaml.load(y)) : undefined;
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
        { manifest, input, eval_mode: evalMode, ...(agents ? { agents } : {}) },
        (ev) => {
          // Live token deltas fill the answer in real time; they are NOT added
          // to the trace/graph (which show structural steps only).
          if (ev.type === "token") {
            setAnswer((prev) => (prev ?? "") + (ev.detail ?? ""));
            return;
          }
          setEvents((prev) => [...prev, ev]);
          // The final "answer" event carries the authoritative full text
          // (post-guardrails when applicable) — overwrite the streamed buffer.
          if (ev.type === "answer") setAnswer(ev.detail ?? "");
          if (ev.type === "error") {
            setRunError(ev.detail ?? "error");
            setStatus("error");
          }
          if (ev.type === "limit") {
            // The run stopped without an answer (step/time budget). Surface the
            // reason instead of silently finishing.
            setRunError(ev.detail ?? "run stopped before answering");
            setStatus((s) => (s === "error" ? s : "stopped"));
          }
          if (ev.type === "done") {
            setCost(ev.cost_usd ?? 0);
            setStatus((s) => (s === "error" || s === "stopped" ? s : "done"));
          }
        },
        ctrl.signal,
      );
      setStatus((s) => (s === "error" || s === "stopped" ? s : "done"));
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
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <LogoMark />
          </span>
          <h1>
            AgentForge
            <span className="brand-sub">Agent Builder</span>
          </h1>
        </div>
        <span className="spacer" />
        <span className="status-chip">
          <span className={`dot ${health ? "ok" : ""}`} data-testid="health-dot" />
          <span className="state">{health ? "Online" : "Offline"}</span>
        </span>
        <span className="meta" data-testid="health-meta">
          {health
            ? `core ${health.core_version} · models: ${health.models.join(", ")} · tools: ${health.tools.length}`
            : "backend offline · core —"}
        </span>
        <ThemeToggle />
      </div>

      <div className="tabbar" role="tablist" aria-label="Primary" onKeyDown={onTabKey}>
        <button
          type="button"
          role="tab"
          id="tab-builder"
          className="tab"
          data-testid="tab-builder"
          aria-selected={tab === "builder"}
          aria-controls="panel-builder"
          tabIndex={tab === "builder" ? 0 : -1}
          onClick={() => setTab("builder")}
        >
          <LayersIcon />
          Builder
        </button>
        <button
          type="button"
          role="tab"
          id="tab-eval"
          className="tab"
          data-testid="tab-eval"
          aria-selected={tab === "eval"}
          aria-controls="panel-eval"
          tabIndex={tab === "eval" ? 0 : -1}
          onClick={() => setTab("eval")}
        >
          <GaugeIcon />
          Eval
        </button>
        <button
          type="button"
          role="tab"
          id="tab-about"
          className="tab"
          data-testid="tab-about"
          aria-selected={tab === "about"}
          aria-controls="panel-about"
          tabIndex={tab === "about" ? 0 : -1}
          onClick={() => setTab("about")}
        >
          <DocIcon />
          About
        </button>
      </div>

      <div
        id="panel-eval"
        role="tabpanel"
        aria-labelledby="tab-eval"
        hidden={tab !== "eval"}
      >
        {tab === "eval" && <EvalPanel manifestYaml={manifestYaml} />}
      </div>

      <div
        id="panel-about"
        role="tabpanel"
        aria-labelledby="tab-about"
        hidden={tab !== "about"}
      >
        {tab === "about" && <AboutPanel />}
      </div>

      <div
        id="panel-builder"
        role="tabpanel"
        aria-labelledby="tab-builder"
        hidden={tab !== "builder"}
      >
      <div className="layout">
        {/* LEFT: authoring */}
        <div className="col">
          <div className="card">
            <h2>
              <span className="h-ico"><DocIcon /></span>
              Manifest
            </h2>
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
                <label className="toggle" htmlFor="evalmode">
                  <input
                    id="evalmode"
                    type="checkbox"
                    checked={evalMode}
                    onChange={(e) => setEvalMode(e.target.checked)}
                  />
                  eval mode
                </label>
              </div>

              <label htmlFor="manifest">YAML</label>
              <textarea
                id="manifest"
                data-testid="manifest-editor"
                value={manifestYaml}
                onChange={(e) => setManifestYaml(e.target.value)}
                spellCheck={false}
              />

              <div className="builder-input">
                <label htmlFor="input">Input</label>
                <input
                  id="input"
                  type="text"
                  data-testid="run-input"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                />
              </div>

              <div className="row builder-actions">
                <button className="secondary" data-testid="validate-btn" onClick={onValidate}>
                  <CheckIcon />
                  Validate
                </button>
                {running ? (
                  <button className="danger" data-testid="stop-btn" onClick={onStop}>
                    <StopIcon />
                    Stop
                  </button>
                ) : (
                  <button data-testid="run-btn" onClick={onRun}>
                    <PlayIcon />
                    Run agent
                  </button>
                )}
              </div>
              {validity && (
                <div className="validity-line">
                  <span className={`pill ${validity.ok ? "ok" : "bad"}`} data-testid="validity">
                    {validity.ok ? "VALID" : "INVALID"}
                  </span>
                  <span className="msg">{validity.msg}</span>
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <h2>
              <span className="h-ico"><HistoryIcon /></span>
              Run history
            </h2>
            <div className="body hist flush" data-testid="run-history">
              {runs.length === 0 && (
                <p className="empty">
                  No runs yet.
                </p>
              )}
              {runs.map((r) => (
                <div className="hist-row" key={r.id}>
                  <span className={`pill ${r.status === "completed" ? "ok" : r.status === "error" ? "bad" : "warn"}`}>
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
        <div className="col">
          <div className="card">
            <h2>
              <span className="h-ico"><OutputIcon /></span>
              Run output
              <span className="h-right">
                {running && <span className="live-dot" aria-hidden="true" />}
                <span
                  className={`pill ${status === "done" ? "ok" : status === "error" ? "bad" : status === "running" || status === "stopped" ? "warn" : ""}`}
                  data-testid="run-status"
                >
                  {status}
                </span>
              </span>
            </h2>
            <div className="body">
              {answer !== null && (
                <div className="answer" data-testid="answer">
                  <div className="lbl">
                    <CheckIcon />
                    Answer
                  </div>
                  {answer}
                </div>
              )}
              {runError && (
                <p className="err" data-testid="run-error">
                  {runError}
                </p>
              )}
              {cost !== null && (
                <p className="cost" data-testid="cost">
                  cost: <span className="num">${cost.toFixed(6)}</span>
                </p>
              )}
              {answer === null && !runError && status === "idle" && (
                <p className="empty">
                  <PlayIcon />
                  Author a manifest and click <b>Run agent</b> to stream the trace.
                </p>
              )}
            </div>
          </div>

          <div className="card">
            <h2>
              <span className="h-ico"><TraceIcon /></span>
              Trace
            </h2>
            <div className="body trace" data-testid="trace">
              {events.length === 0 && (
                <p className="empty">
                  No events yet.
                </p>
              )}
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
                      <ToolIcon />
                      {tc.name}({JSON.stringify(tc.args)})
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h2>
              <span className="h-ico"><GraphIcon /></span>
              3D execution graph
            </h2>
            <div className="body flush" data-testid="trace-3d">
              <TraceGraph3D events={events} status={status} />
            </div>
          </div>
        </div>
      </div>
      </div>
    </>
  );
}
