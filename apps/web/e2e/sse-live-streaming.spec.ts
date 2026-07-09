import { test, expect } from "@playwright/test";

// Regression: SSE trace events must render INCREMENTALLY while the run is still
// in progress — not buffered and dumped only at completion (the gzip-buffering
// bug fixed by `compress: false`). Live run → gated behind SKIP_LIVE.
test("SSE trace renders live during the run, not only at the end", async ({ page }) => {
  test.skip(!!process.env.SKIP_LIVE, "live run disabled");
  await page.goto("/");
  await page.getByTestId("template-select").selectOption("assistant");
  await page.getByTestId("run-input").fill("give me info about world cup 2026 right now");
  await page.getByTestId("run-btn").click();

  // At least one trace event must be visible WHILE status is still "running".
  await expect
    .poll(
      async () => {
        const running = (await page.getByTestId("run-status").textContent()) === "running";
        const events = await page.getByTestId(/^event-/).count();
        return running && events > 0 ? "live" : "not-yet";
      },
      { timeout: 30_000, intervals: [300] },
    )
    .toBe("live");

  await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 60_000 });
});
