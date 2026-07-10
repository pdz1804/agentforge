import { test, expect } from "@playwright/test";

const SHOTS = "../../../plans/260709-1427-dual-app-buildout/reports/agentforge-ui/screens";

// Regression coverage for the "world cup 2026 right now" error report:
// (A) the query answers normally on the default assistant template;
// (B) when the step budget is exhausted the UI shows a clear "stopped" state
//     with the reason — never a silent no-answer or a misleading error.
test.describe("world cup 2026 query", () => {
  test("A: answers normally (default template)", async ({ page }) => {
    // Live run: needs a real OpenAI key + Tavily (web_search). Gated behind
    // SKIP_LIVE so it self-skips with a clear reason in CI (no keys) instead of
    // failing, matching the SKIP_LIVE pattern used by the other live specs.
    test.skip(!!process.env.SKIP_LIVE, "live run disabled — needs OPENAI_API_KEY + Tavily");
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/");
    await page.getByTestId("template-select").selectOption("assistant");
    await page.getByTestId("run-input").fill("give me info about world cup 2026 right now ");
    await page.getByTestId("run-btn").click();
    await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 80_000 });
    await expect(page.getByTestId("answer")).toBeVisible();
    expect(errors).toEqual([]);
    await page.screenshot({ path: `${SHOTS}/wc2026-answered.png`, fullPage: true });
  });

  test("B: step-budget exhaustion shows a clear stopped state (not error)", async ({ page }) => {
    // Live run (OpenAI + web_search). Gated behind SKIP_LIVE like case A above.
    test.skip(!!process.env.SKIP_LIVE, "live run disabled — needs OPENAI_API_KEY + Tavily");
    await page.goto("/");
    await page.getByTestId("template-select").selectOption("assistant");
    // Force the pathological case: only one step, so the model's tool request
    // can never be answered within budget.
    const yaml = `id: assistant
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
tools:
  - web_search
limits:
  max_steps: 1
`;
    await page.getByTestId("manifest-editor").fill(yaml);
    await page.getByTestId("run-input").fill("give me info about world cup 2026 right now ");
    await page.getByTestId("run-btn").click();
    await expect(page.getByTestId("run-status")).toHaveText("stopped", { timeout: 80_000 });
    await expect(page.getByTestId("run-error")).toContainText(/max_steps|increase limits/i);
    await page.screenshot({ path: `${SHOTS}/wc2026-stopped.png`, fullPage: true });
  });
});
