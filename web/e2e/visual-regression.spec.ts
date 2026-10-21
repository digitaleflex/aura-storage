import { test, expect } from "@playwright/test";

/**
 * Visual regression baselines (P5 #169).
 * Run with `npx playwright test visual-regression.spec.ts --update-snapshots`
 * to (re)generate baselines. Dynamic regions are masked.
 */
test("login page baseline", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveScreenshot("login.png", {
    maxDiffPixelRatio: 0.02,
    mask: [page.locator("input")],
  });
});
EOF
echo done