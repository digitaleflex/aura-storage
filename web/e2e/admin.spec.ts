import { test, expect } from "@playwright/test";

/**
 * Read-only administration console (`admin:read`).
 *
 * Requires the local API (uvicorn 127.0.0.1:8081, SQLite :memory:, dummy S3
 * creds and AURA_API_ADMIN_PASSWORD=local-smoke-test-password as documented in
 * web/README.md) and the Vite dev server (127.0.0.1:5173). The console only
 * issues GETs; no S3 contact and no mutation happens here.
 */

test("admin route requires authentication", async ({ page }) => {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login/);
});

test("admin can open the read-only console", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();

  // Admin nav entry only appears for an operator/admin role.
  const adminLink = page.getByRole("link", { name: "Administration" });
  await expect(adminLink).toBeVisible();
  await adminLink.click();

  await expect(page).toHaveURL(/\/admin/);
  await expect(
    page.getByRole("heading", { name: "Tableau de bord" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Identités machine-à-machine" }),
  ).toBeVisible();
});
