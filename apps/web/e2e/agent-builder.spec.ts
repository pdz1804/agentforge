import { test, expect } from "@playwright/test";

const SHOTS = "../../../plans/260709-1427-dual-app-buildout/reports/agentforge-ui/screens";

test.describe("AgentForge Agent Builder UI", () => {
  test("backend online + page loads", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /AgentForge/ })).toBeVisible();
    // Health handshake proxied through Next to the FastAPI backend.
    await expect(page.getByTestId("health-meta")).toContainText("core", { timeout: 15_000 });
    await expect(page.getByTestId("health-dot")).toHaveClass(/ok/);
    await page.screenshot({ path: `${SHOTS}/01-loaded.png`, fullPage: true });
  });

  test("validate manifest", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("validate-btn").click();
    await expect(page.getByTestId("validity")).toHaveText("VALID", { timeout: 15_000 });
    await page.screenshot({ path: `${SHOTS}/02-validated.png`, fullPage: true });
  });

  test("echo run streams answer + trace + graph (deterministic)", async ({ page }) => {
    await page.goto("/");
    // Echo template is selected by default; run it.
    await page.getByTestId("run-btn").click();
    await expect(page.getByTestId("answer")).toContainText("hello agentforge", { timeout: 30_000 });
    await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 30_000 });
    await expect(page.getByTestId("event-answer")).toBeVisible();
    // 3D graph or its 2D fallback must render.
    const graph = page.locator('[data-testid="trace-3d-canvas"], [data-testid="trace-2d-fallback"]');
    await expect(graph.first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: `${SHOTS}/03-echo-run.png`, fullPage: true });
  });

  test("live OpenAI + web_search run (evidence)", async ({ page }) => {
    test.skip(!!process.env.SKIP_LIVE, "live run disabled");
    await page.goto("/");
    await page.getByTestId("template-select").selectOption("assistant");
    await page.getByTestId("run-btn").click();
    // Real model→tool→answer loop; give it time.
    await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 80_000 });
    await expect(page.getByTestId("answer")).toBeVisible();
    // A tool event must have streamed (web_search).
    await expect(page.getByTestId("event-tool").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/04-live-openai-run.png`, fullPage: true });
  });
});
