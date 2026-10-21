import { test, expect } from "@playwright/test";

/**
 * Administration console.
 *
 * `admin:read` unlocks the registries (stats, applications, spaces, identities);
 * `admin:write` additionally reveals the mutation controls (create application /
 * space / identity, rotate, revoke, reconcile). The `admin` account holds both.
 *
 * Requires the local API (uvicorn 127.0.0.1:8081, SQLite :memory:, dummy S3
 * creds and AURA_API_ADMIN_PASSWORD=local-smoke-test-password as documented in
 * web/README.md) and the Vite dev server (127.0.0.1:5173). No mutation is sent
 * and no S3 contact happens in these tests.
 */

test("admin route requires authentication", async ({ page }) => {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login/);
});

test("admin can open the console and sees the write controls", async ({ page }) => {
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
  // One tab per section: the overview is open first, the others on demand.
  await expect(page.getByRole("tab", { selected: true })).toHaveText("Vue d'ensemble");
  await page.getByRole("tab", { name: "Identités de service" }).click();
  await expect(
    page.getByRole("heading", { name: "Identités machine-à-machine" }),
  ).toBeVisible();

  // `admin:write`: the create-identity form is present (server stays authoritative).
  await expect(
    page.getByRole("button", { name: "Créer l'identité" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Applications et espaces" }).click();
  await expect(
    page.getByRole("button", { name: "Créer l'espace" }),
  ).toBeVisible();
});
