import { test, expect } from "@playwright/test";

const SHOTS = "../../../plans/260709-1427-dual-app-buildout/reports/agentforge-ui/screens";

test.describe("AgentForge theme + tabs", () => {
  test("theme toggle cycles and persists; tabs switch", async ({ page }) => {
    await page.goto("/");
    await page.screenshot({ path: `${SHOTS}/theme-dark.png`, fullPage: true });

    // Cycle the theme until the document is explicitly light, then verify it applied.
    const toggle = page.getByTestId("theme-toggle");
    await expect(toggle).toBeVisible();
    for (let i = 0; i < 3; i++) {
      const theme = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
      if (theme === "light") break;
      await toggle.click();
    }
    await expect
      .poll(() => page.evaluate(() => document.documentElement.getAttribute("data-theme")))
      .toBe("light");
    await page.screenshot({ path: `${SHOTS}/theme-light.png`, fullPage: true });

    // About tab.
    await page.getByTestId("tab-about").click();
    await expect(page.getByTestId("about-page")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/about-page.png`, fullPage: true });

    // Persistence across reload.
    await page.reload();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.getAttribute("data-theme")))
      .toBe("light");

    // Back to Builder tab keeps the run panel.
    await page.getByTestId("tab-builder").click();
    await expect(page.getByTestId("manifest-editor")).toBeVisible();
  });
});
