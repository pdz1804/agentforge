import { test, expect } from "@playwright/test";

const SHOTS = "../../../plans/260709-1427-dual-app-buildout/reports/agentforge-ui/screens";

test("eval tab runs the offline echo suite → dev/held-out report", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("tab-eval").click();
  await expect(page.getByTestId("eval-panel")).toBeVisible({ timeout: 15_000 });
  // Default suite selection is the offline echo suite (free) per the panel.
  await page.getByTestId("eval-run").click();
  await expect(page.getByTestId("eval-report")).toBeVisible({ timeout: 40_000 });
  await page.screenshot({ path: `${SHOTS}/eval-report.png`, fullPage: true });
});
