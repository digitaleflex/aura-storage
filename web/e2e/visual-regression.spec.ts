import { test, expect } from "@playwright/test";

// Baselines are generated on the reference host (fonts, hinting, OS rasterizer).
// Running them on the GitHub runner produces false diffs, so the functional e2e
// suite runs there and the visual suite stays a local/reference-host gate.
test.skip(!!process.env.CI, "visual baselines are reference-host specific");

/**
 * Visual regression tests for AURA Vault key pages.
 *
 * These tests capture screenshots and compare them against baselines.
 * Dynamic regions (usage data, timestamps, toasts) are masked to avoid flakiness.
 *
 * Run with: npx playwright test e2e/visual-regression.spec.ts
 * Update baselines: npx playwright test e2e/visual-regression.spec.ts --update-snapshots
 */

test.describe("Visual regression — Login", () => {
  test("login page desktop", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("login-desktop.png", {
      fullPage: true,
      maxDiffPixels: 50,
      mask: [page.locator(".spinner")],
    });
  });

  test("login page mobile", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("login-mobile.png", {
      fullPage: true,
      maxDiffPixels: 50,
      mask: [page.locator(".spinner")],
    });
  });
});

test.describe("Visual regression — Mes fichiers", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Identifiant").fill("admin");
    await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
    await page.getByRole("button", { name: "Se connecter", exact: true }).click();
    await page.waitForURL("/");
  });

  test("files page desktop", async ({ page }) => {
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("files-desktop.png", {
      fullPage: false,
      maxDiffPixels: 50,
      mask: [
        page.locator(".sidebar-foot span"),
        page.locator(".visually-hidden"),
        page.locator(".spinner"),
      ],
    });
  });

  test("files page mobile", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("files-mobile.png", {
      fullPage: false,
      maxDiffPixels: 50,
      mask: [
        page.locator(".sidebar-foot span"),
        page.locator(".visually-hidden"),
        page.locator(".spinner"),
      ],
    });
  });
});

test.describe("Visual regression — Administration", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Identifiant").fill("admin");
    await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
    await page.getByRole("button", { name: "Se connecter", exact: true }).click();
    await page.getByRole("link", { name: "Administration" }).click();
    await page.waitForURL("/admin");
  });

  test("admin page desktop", async ({ page }) => {
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("admin-desktop.png", {
      fullPage: false,
      maxDiffPixels: 500,
      mask: [
        page.locator(".visually-hidden"),
        page.locator(".spinner"),
        page.locator(".stat"),
        page.locator(".table"),
        page.locator(".token-value"),
        page.locator(".tabs"),
      ],
    });
  });

  test("admin page mobile", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("admin-mobile.png", {
      fullPage: false,
      maxDiffPixels: 500,
      mask: [
        page.locator(".visually-hidden"),
        page.locator(".spinner"),
        page.locator(".stat"),
        page.locator(".table"),
        page.locator(".token-value"),
        page.locator(".tabs"),
      ],
    });
  });
});