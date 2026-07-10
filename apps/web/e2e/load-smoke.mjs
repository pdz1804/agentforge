#!/usr/bin/env node
// Lightweight load / p95 smoke gate — no external dependencies (uses Node >=18's
// global fetch + performance.now). NOT a benchmark: it fires a bounded burst of
// requests at a single endpoint, drains each full response body, and asserts
// (a) every request returned the expected status and (b) p95 wall-clock latency
// stays under a generous threshold. A regression that makes the hot path an
// order of magnitude slower, or that starts erroring under trivial concurrency,
// trips this gate; normal timing jitter does not.
//
// Usage:
//   node load-smoke.mjs --url http://127.0.0.1:8077/api/runs \
//     --method POST --body-file body.json --count 40 --concurrency 8 --p95 4000
//   node load-smoke.mjs --url http://127.0.0.1:8100/health --count 60 --p95 1500
//
// Flags: --url (required) --method (GET) --count (40) --concurrency (8)
//        --p95 <ms> (4000) --body <json> | --body-file <path> --expect-status (200)

import { readFileSync } from "node:fs";

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}

const url = arg("url");
const method = arg("method", "GET").toUpperCase();
const count = parseInt(arg("count", "40"), 10);
const concurrency = parseInt(arg("concurrency", "8"), 10);
const p95Threshold = parseInt(arg("p95", "4000"), 10);
const expectStatus = parseInt(arg("expect-status", "200"), 10);
const bodyFile = arg("body-file");
const bodyInline = arg("body");

if (!url) {
  console.error("load-smoke: --url is required");
  process.exit(2);
}

const body = bodyFile ? readFileSync(bodyFile, "utf8") : bodyInline;
const headers = {};
if (method !== "GET" && body) headers["Content-Type"] = "application/json";

const latencies = [];
let failures = 0;
let cursor = 0;

async function oneRequest() {
  const t0 = performance.now();
  try {
    const res = await fetch(url, {
      method,
      headers,
      body: method === "GET" ? undefined : body,
    });
    // Drain the full body so the measured latency covers the whole response
    // (important for the SSE run endpoint, which returns 200 immediately then
    // streams the trace — a status-only check would time nothing meaningful).
    await res.arrayBuffer();
    const dt = performance.now() - t0;
    if (res.status !== expectStatus) {
      failures++;
      console.error(`  request failed: HTTP ${res.status} (expected ${expectStatus})`);
    } else {
      latencies.push(dt);
    }
  } catch (err) {
    failures++;
    console.error(`  request error: ${err && err.message ? err.message : err}`);
  }
}

async function worker() {
  for (;;) {
    const i = cursor++;
    if (i >= count) return;
    await oneRequest();
  }
}

function percentile(p) {
  if (latencies.length === 0) return NaN;
  const idx = Math.min(latencies.length - 1, Math.ceil((p / 100) * latencies.length) - 1);
  return latencies[idx];
}

const startedAt = performance.now();
await Promise.all(Array.from({ length: Math.max(1, concurrency) }, worker));
const wall = performance.now() - startedAt;

latencies.sort((a, b) => a - b);
const p50 = percentile(50);
const p95 = percentile(95);
const max = latencies.length ? latencies[latencies.length - 1] : NaN;
const throughput = latencies.length / (wall / 1000);

console.log(`load-smoke ${method} ${url}`);
console.log(
  `  requests=${count} concurrency=${concurrency} ok=${latencies.length} failed=${failures}`,
);
console.log(
  `  latency(ms) p50=${p50.toFixed(0)} p95=${p95.toFixed(0)} max=${max.toFixed(0)} | ~${throughput.toFixed(1)} req/s over ${wall.toFixed(0)}ms`,
);
console.log(`  gate: p95 <= ${p95Threshold}ms, all requests == HTTP ${expectStatus}`);

let failed = false;
if (failures > 0) {
  console.error(`FAIL: ${failures} request(s) did not return HTTP ${expectStatus}`);
  failed = true;
}
if (latencies.length === 0) {
  console.error("FAIL: no successful requests to measure");
  failed = true;
} else if (!(p95 <= p95Threshold)) {
  console.error(`FAIL: p95 ${p95.toFixed(0)}ms exceeds threshold ${p95Threshold}ms`);
  failed = true;
}

console.log(failed ? "load-smoke: FAIL" : "load-smoke: PASS");
// Prefer setting exitCode + letting the loop drain over a hard process.exit():
// exiting abruptly while fetch's keep-alive sockets are still closing trips a
// libuv assertion on Windows. Proactively close fetch's global connection pool
// so the process exits promptly instead of waiting out the keep-alive timeout.
process.exitCode = failed ? 1 : 0;
try {
  const dispatcher = globalThis[Symbol.for("undici.globalDispatcher.1")];
  if (dispatcher && typeof dispatcher.close === "function") await dispatcher.close();
} catch {
  /* best-effort: if the pool can't be closed, the keep-alive timeout still ends it */
}
