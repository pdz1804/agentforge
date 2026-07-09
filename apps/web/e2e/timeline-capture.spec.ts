import { test, expect } from "@playwright/test";

const SHOTS = "../../../plans/260709-1427-dual-app-buildout/reports/agentforge-ui/screens";

test("3D graph + timeline scrubber after a run", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("run-btn").click(); // echo (default template)
  await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 30_000 });
  await expect(page.getByTestId("trace-timeline")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("trace-3d").scrollIntoViewIfNeeded();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/trace-timeline.png`, fullPage: true });
});
