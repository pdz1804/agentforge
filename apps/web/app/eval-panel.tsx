"use client";

// Eval report view (PRD Phase 9). Runs the eval harness on the manifest the
// Builder tab currently holds and renders the dev vs held-out report side by
// side. Additive UI only — it reuses the shared design tokens/classes.

import { useEffect, useMemo, useState } from "react";
import yaml from "js-yaml";
import {
  listSuites,
  runEval,
  promoteBaseline,
  getSpotCheck,
  type EvalSuite,
  type EvalResponse,
  type RegressionVerdict,
  type SplitReport,
  type SpotCheckResponse,
} from "@/lib/api";
import {
  CheckIcon,
  CoinIcon,
  FlaskIcon,
  GaugeIcon,
  PlayIcon,
  SpinnerIcon,
  TargetIcon,
} from "./icons";

// A suite is "offline" (free to run) when it grades against the echo agent —
// no LLM provider is billed. Everything else is flagged as live ($).
function isOffline(s: EvalSuite): boolean {
  return `${s.suite_id} ${s.manifest_id}`.toLowerCase().includes("echo");
}

function pct(n?: number): string {
  if (n == null || Number.isNaN(n)) return "—";
  // pass_rate arrives as a 0..1 fraction; tolerate an already-percent value.
  const v = n <= 1 ? n * 100 : n;
  return `${Math.round(v)}%`;
}

function num(n?: number): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(3);
}

// Prefer server-provided stats; fall back to deriving them from task_scores so
// the summary is never blank when a split still carries per-task results.
function splitStats(s: SplitReport) {
  const tasks = s.task_scores ?? [];
  const total = tasks.length;
  const passed = tasks.filter((t) => t.passed).length;
  const passRate = s.pass_rate != null ? s.pass_rate : total ? passed / total : undefined;
  const mean =
    s.mean_score != null
      ? s.mean_score
      : total
        ? tasks.reduce((a, t) => a + (Number(t.score) || 0), 0) / total
        : undefined;
  return { total, passed, passRate, mean };
}

function prettySplit(split: string): string {
  return split.replace(/_/g, "-");
}

function SplitCard({ report, held }: { report: SplitReport; held: boolean }) {
  const st = splitStats(report);
  const tasks = report.task_scores ?? [];
  return (
    <div className="eval-split" data-testid={`eval-split-${report.split}`}>
      <div className="eval-split-head">
        <span className="es-ico">{held ? <TargetIcon /> : <FlaskIcon />}</span>
        <div className="es-title">
          <span className="es-name">{prettySplit(report.split)}</span>
          <span className="es-sub">{held ? "generalization" : "iteration"}</span>
        </div>
        <span className="es-count">{st.total} tasks</span>
      </div>

      <div className="eval-metrics">
        <div className="metric">
          <span className="m-val">{pct(st.passRate)}</span>
          <span className="m-lbl">Pass rate</span>
        </div>
        <div className="metric">
          <span className="m-val">{num(st.mean)}</span>
          <span className="m-lbl">Mean score</span>
        </div>
        <div className="metric">
          <span className="m-val">
            {st.passed}
            <span className="m-of">/{st.total}</span>
          </span>
          <span className="m-lbl">Passed</span>
        </div>
      </div>

      <div className="eval-tasks" role="table" aria-label={`${report.split} tasks`}>
        <div className="et-row et-head" role="row">
          <span role="columnheader">Task</span>
          <span role="columnheader">Score</span>
          <span role="columnheader">Result</span>
        </div>
        {tasks.length === 0 && <p className="empty et-empty">No task scores.</p>}
        {tasks.map((t) => (
          <div className="et-row" role="row" key={t.task_id}>
            <span className="et-id" role="cell" title={t.task_id}>
              {t.task_id}
            </span>
            <span className="et-score" role="cell">
              {num(Number(t.score))}
            </span>
            <span role="cell">
              <span className={`pill ${t.passed ? "ok" : "bad"}`}>{t.passed ? "PASS" : "FAIL"}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RegressionBanner({ reg }: { reg: RegressionVerdict }) {
  // Derive a headline verdict defensively. The backend's RegressionResult
  // reports `blocked` (true = a real regression that blocks promotion), so a
  // clean run is verdict=true (NO REGRESSION). Fall back to older/alternate
  // boolean shapes if a different backend build ever sends them.
  const verdict =
    typeof reg.blocked === "boolean"
      ? !reg.blocked
      : reg.passed ?? reg.ok ?? (reg.regressed != null ? !reg.regressed : undefined);
  const entries = Object.entries(reg).filter(
    ([, v]) => typeof v === "string" || typeof v === "number" || typeof v === "boolean",
  );
  return (
    <div
      className={`eval-regression ${verdict === false ? "bad" : verdict === true ? "ok" : ""}`}
      data-testid="eval-regression"
    >
      <div className="er-head">
        <GaugeIcon />
        <span className="er-title">Regression vs baseline</span>
        {verdict != null && (
          <span className={`pill ${verdict ? "ok" : "bad"}`}>
            {verdict ? "NO REGRESSION" : "REGRESSION"}
          </span>
        )}
      </div>
      {entries.length > 0 && (
        <div className="er-facts">
          {entries.map(([k, v]) => (
            <span className="er-fact" key={k}>
              <span className="erf-k">{k.replace(/_/g, " ")}</span>
              <span className="erf-v">{String(v)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function EvalPanel({ manifestYaml }: { manifestYaml: string }) {
  const [suites, setSuites] = useState<EvalSuite[] | null>(null);
  const [suitesError, setSuitesError] = useState<string | null>(null);
  const [suiteId, setSuiteId] = useState<string>("");
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [result, setResult] = useState<EvalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Eval-gate UX: opt into gating the next run against the manifest's stored
  // baseline, and promote the freshest report to become that baseline.
  const [compareBaseline, setCompareBaseline] = useState(false);
  const [promote, setPromote] = useState<{
    status: "idle" | "saving" | "saved" | "error";
    message: string | null;
  }>({ status: "idle", message: null });

  // Human spot-check viewer for llm_judge suites — lazily fetched per report.
  const [spotOpen, setSpotOpen] = useState(false);
  const [spot, setSpot] = useState<SpotCheckResponse | null>(null);
  const [spotStatus, setSpotStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [spotError, setSpotError] = useState<string | null>(null);

  // Parsed manifest id for display — evals always run against the CURRENT
  // Builder manifest, so surface which one and any YAML problem up front.
  const parsed = useMemo(() => {
    try {
      const m = yaml.load(manifestYaml) as { id?: string } | null;
      return { manifest: m, id: (m && m.id) || null, error: null as string | null };
    } catch (e) {
      return { manifest: null, id: null, error: (e as Error).message };
    }
  }, [manifestYaml]);

  useEffect(() => {
    let alive = true;
    listSuites()
      .then((s) => alive && setSuites(s))
      .catch((e) => alive && setSuitesError((e as Error).message));
    return () => {
      alive = false;
    };
  }, []);

  // Auto-select the suite that matches the CURRENT manifest id — evals require
  // manifest.id === suite.manifest_id, so a mismatched default (e.g. the offline
  // echo suite while the Builder holds the assistant manifest) would only fail
  // on Run. Prefer an offline match so a click never bills by surprise, and
  // re-run when the manifest changes so switching templates re-picks correctly.
  useEffect(() => {
    if (!suites || suites.length === 0) return;
    const matching = suites.filter((s) => s.manifest_id === parsed.id);
    const pick = matching.find(isOffline) ?? matching[0] ?? suites.find(isOffline) ?? suites[0];
    if (pick) setSuiteId(pick.suite_id);
  }, [suites, parsed.id]);

  const selected = suites?.find((s) => s.suite_id === suiteId) ?? null;
  const live = selected ? !isOffline(selected) : false;
  // A suite only grades the manifest it was written for.
  const idMismatch =
    selected != null && parsed.id != null && selected.manifest_id !== parsed.id;

  async function onRun() {
    if (parsed.error) {
      setError(`YAML parse error: ${parsed.error}`);
      setStatus("error");
      return;
    }
    if (!suiteId) return;
    if (idMismatch) {
      setError(
        `This suite grades manifest "${selected!.manifest_id}", but the Builder manifest is ` +
          `"${parsed.id}". Load the "${selected!.manifest_id}" manifest, or pick a suite for ` +
          `"${parsed.id}".`,
      );
      setStatus("error");
      return;
    }
    setStatus("running");
    setError(null);
    setResult(null);
    // A fresh run invalidates the previous report's baseline/spot-check state.
    setPromote({ status: "idle", message: null });
    setSpot(null);
    setSpotStatus("idle");
    setSpotError(null);
    setSpotOpen(false);
    try {
      const res = await runEval({
        manifest: parsed.manifest,
        suite_id: suiteId,
        use_stored_baseline: compareBaseline,
      });
      setResult(res);
      setStatus("done");
    } catch (e) {
      const msg = (e as Error).message;
      // The gate 404s when no baseline has been promoted for this manifest yet —
      // point the user at the "Set as baseline" button instead of the raw detail.
      setError(
        compareBaseline && /no stored baseline/i.test(msg)
          ? `No stored baseline for this manifest yet. Run without comparing, then click ` +
              `"Set as baseline" to store one — future runs can then compare against it.`
          : msg,
      );
      setStatus("error");
    }
  }

  async function onPromote() {
    const reportId = result?.report_id;
    if (!reportId) return;
    setPromote({ status: "saving", message: null });
    try {
      const res = await promoteBaseline(reportId);
      setPromote({
        status: "saved",
        message: `Baseline saved for ${res.manifest_id} (held-out pass rate ${pct(
          res.baseline_pass_rate,
        )}). Enable "compare vs stored baseline" and re-run to gate against it.`,
      });
    } catch (e) {
      setPromote({ status: "error", message: (e as Error).message });
    }
  }

  async function onToggleSpotCheck() {
    const next = !spotOpen;
    setSpotOpen(next);
    // Lazily fetch on first open for the current report.
    if (next && spotStatus === "idle" && result?.report_id) {
      setSpotStatus("loading");
      setSpotError(null);
      try {
        const res = await getSpotCheck(result.report_id);
        setSpot(res);
        setSpotStatus("done");
      } catch (e) {
        setSpotError((e as Error).message);
        setSpotStatus("error");
      }
    }
  }

  const running = status === "running";

  return (
    <div className="eval" data-testid="eval-panel">
      <div className="eval-wrap">
        {/* ---- Controls ---- */}
        <div className="card">
          <h2>
            <span className="h-ico">
              <GaugeIcon />
            </span>
            Eval harness
          </h2>
          <div className="body">
            <p className="eval-lede">
              Grade the <b>current Builder manifest</b> against a suite and compare the{" "}
              <b>dev</b> split (iterate) with the <b>held-out</b> split (generalization).
            </p>

            <div className="eval-controls">
              <div className="eval-suite-field">
                <label htmlFor="eval-suite">Suite</label>
                {suitesError ? (
                  <p className="err" style={{ margin: 0 }} data-testid="eval-suites-error">
                    Could not load suites: {suitesError}
                  </p>
                ) : suites === null ? (
                  <p className="empty" style={{ margin: 0 }}>
                    <SpinnerIcon className="spin" />
                    Loading suites…
                  </p>
                ) : suites.length === 0 ? (
                  <p className="empty" style={{ margin: 0 }}>
                    No eval suites registered.
                  </p>
                ) : (
                  <select
                    id="eval-suite"
                    data-testid="eval-suite-select"
                    value={suiteId}
                    onChange={(e) => setSuiteId(e.target.value)}
                    disabled={running}
                  >
                    {suites.map((s) => (
                      <option key={s.suite_id} value={s.suite_id}>
                        {s.suite_id} · for {s.manifest_id} · {s.dev_task_count}+
                        {s.held_out_task_count} tasks{isOffline(s) ? "  (offline)" : "  (live $)"}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <button
                data-testid="eval-run"
                onClick={onRun}
                disabled={
                  running || !suiteId || suites === null || suites?.length === 0 || idMismatch
                }
              >
                {running ? <SpinnerIcon className="spin" /> : <PlayIcon />}
                {running ? "Running…" : "Run eval"}
              </button>

              <label
                className="eval-gate-toggle"
                title="Gate this run against the manifest's stored baseline"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 12,
                  color: "var(--ink-soft)",
                  cursor: running ? "not-allowed" : "pointer",
                }}
              >
                <input
                  type="checkbox"
                  data-testid="eval-compare-baseline"
                  checked={compareBaseline}
                  onChange={(e) => setCompareBaseline(e.target.checked)}
                  disabled={running}
                />
                compare vs stored baseline
              </label>
            </div>

            <div className="eval-meta">
              <span className="pill info" title="Evals run against the manifest in the Builder tab">
                {parsed.id ? `manifest: ${parsed.id}` : "manifest: (unnamed)"}
              </span>
              {selected && (
                <span className={`pill ${live ? "warn" : "ok"}`} data-testid="eval-cost-badge">
                  {live ? "LIVE · COSTS LLM $" : "OFFLINE · FREE"}
                </span>
              )}
            </div>

            {parsed.error && (
              <p className="err" data-testid="eval-yaml-error">
                YAML parse error: {parsed.error}
              </p>
            )}
            {idMismatch && (
              <p className="eval-warn" data-testid="eval-manifest-mismatch">
                <GaugeIcon />
                This suite grades manifest <b>{selected!.manifest_id}</b>, but the Builder manifest
                is <b>{parsed.id}</b>. They must match — load the <b>{selected!.manifest_id}</b>{" "}
                manifest, or pick a suite for <b>{parsed.id}</b>.
              </p>
            )}
            {live && !idMismatch && (
              <p className="eval-warn">
                <CoinIcon />
                This suite grades with a paid model. Each run bills your provider — the offline{" "}
                <b>echo_agent</b> suite is free.
              </p>
            )}
          </div>
        </div>

        {/* ---- Report ---- */}
        <div className="card">
          <h2>
            <span className="h-ico">
              <CheckIcon />
            </span>
            Report
            <span className="h-right">
              <span
                className={`pill ${
                  status === "done" ? "ok" : status === "error" ? "bad" : status === "running" ? "warn" : ""
                }`}
                data-testid="eval-status"
              >
                {status}
              </span>
            </span>
          </h2>
          <div className="body" data-testid="eval-report">
            {status === "idle" && (
              <p className="empty">
                <GaugeIcon />
                Pick a suite and click <b>&nbsp;Run eval&nbsp;</b> to score dev vs held-out.
              </p>
            )}
            {status === "running" && (
              <p className="empty" data-testid="eval-loading">
                <SpinnerIcon className="spin" />
                Scoring suite — dev then held-out…
              </p>
            )}
            {status === "error" && (
              <p className="err" data-testid="eval-error">
                {error}
              </p>
            )}
            {status === "done" && result && (
              <>
                {result.regression && <RegressionBanner reg={result.regression} />}
                <div className="eval-splits">
                  <SplitCard report={result.report.dev} held={false} />
                  <SplitCard report={result.report.held_out} held />
                </div>

                {result.report_id && (
                  <div
                    className="eval-gate"
                    style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 12 }}
                  >
                    <div
                      className="eval-gate-actions"
                      style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}
                    >
                      <button
                        className="secondary"
                        data-testid="eval-promote"
                        onClick={onPromote}
                        disabled={promote.status === "saving"}
                      >
                        {promote.status === "saving" ? (
                          <SpinnerIcon className="spin" />
                        ) : (
                          <TargetIcon />
                        )}
                        {promote.status === "saving" ? "Saving…" : "Set as baseline"}
                      </button>
                      {promote.status === "saved" && promote.message && (
                        <span
                          data-testid="eval-promote-status"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            fontSize: 12,
                            color: "var(--ok)",
                          }}
                        >
                          <CheckIcon /> {promote.message}
                        </span>
                      )}
                      {promote.status === "error" && promote.message && (
                        <span className="err" data-testid="eval-promote-error">
                          {promote.message}
                        </span>
                      )}
                    </div>

                    <div className="eval-spot" data-testid="eval-spot-check">
                      <button
                        className="secondary"
                        data-testid="eval-spot-check-toggle"
                        aria-expanded={spotOpen}
                        onClick={onToggleSpotCheck}
                      >
                        <FlaskIcon />
                        {spotOpen ? "Hide" : "Show"} judge spot-check
                      </button>
                      {spotOpen && (
                        <div className="eval-spot-body" style={{ marginTop: 10 }}>
                          {spotStatus === "loading" && (
                            <p className="empty" style={{ margin: 0 }}>
                              <SpinnerIcon className="spin" />
                              Loading judged samples…
                            </p>
                          )}
                          {spotStatus === "error" && (
                            <p className="err" data-testid="eval-spot-check-error">
                              {spotError}
                            </p>
                          )}
                          {spotStatus === "done" && spot && spot.samples.length === 0 && (
                            <p className="empty" style={{ margin: 0 }}>
                              No llm-judge samples — this suite scores deterministically, so no
                              human audit is needed.
                            </p>
                          )}
                          {spotStatus === "done" && spot && spot.samples.length > 0 && (
                            <div
                              className="eval-tasks"
                              aria-label="judge spot-check samples"
                              style={{ gap: 8, maxHeight: 360 }}
                            >
                              {spot.samples.map((s) => (
                                <div
                                  key={`${s.split}-${s.task_id}`}
                                  style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: 4,
                                    padding: "8px 14px",
                                    borderBottom: "1px solid var(--line-soft)",
                                  }}
                                >
                                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                    <span className="et-id" title={s.task_id} style={{ flex: 1 }}>
                                      {s.task_id}
                                      <span className="es-sub"> · {prettySplit(s.split)}</span>
                                    </span>
                                    <span className={`pill ${s.passed ? "ok" : "bad"}`}>
                                      {s.passed ? "PASS" : "FAIL"} {num(s.judge_score)}
                                    </span>
                                    <span className="pill info" title="human audit status">
                                      {s.review_status ?? "—"}
                                    </span>
                                  </div>
                                  <p
                                    className="es-sub"
                                    style={{ margin: 0 }}
                                    title={s.input}
                                  >
                                    <b>input:</b> {s.input}
                                  </p>
                                  <p
                                    style={{ margin: 0, fontSize: 12, color: "var(--ink-soft)" }}
                                    title={s.judge_detail || undefined}
                                  >
                                    <b>answer:</b> {s.answer ?? "—"}
                                  </p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
