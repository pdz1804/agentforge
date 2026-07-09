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
    screenshot: "on",
    video: "on",
    trace: "on",
    // SwiftShader gives headless Chromium a software WebGL context so the 3D
    // graph renders instead of falling back.
    launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
