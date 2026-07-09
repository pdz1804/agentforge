import { defineConfig, devices } from "@playwright/test";

// Evidence (screenshots/video/HTML report) is written into the plan's reports
// folder so it lands with the rest of the verification artifacts.
const EVIDENCE = "../../../plans/260709-1427-dual-app-buildout/reports/agentforge-ui";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  retries: 0,
  reporter: [
    ["list"],
    ["html", { outputFolder: `${EVIDENCE}/html-report`, open: "never" }],
  ],
  outputDir: `${EVIDENCE}/artifacts`,
  use: {
    baseURL: process.env.WEB_BASE || "http://localhost:3000",
    // Explicit page.screenshot() calls are the primary evidence; video/trace are
    // kept only on failure to avoid per-test recording overhead (which inflated
    // run times and caused timing flakes).
    screenshot: "on",
    video: "retain-on-failure",
    trace: "retain-on-failure",
    // SwiftShader gives headless Chromium a software WebGL context so the 3D
    // graph renders instead of falling back.
    launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
