import { test, expect } from "@playwright/test";

/**
 * Administration mutations (`admin:write`): create an application, a space and a
 * machine identity, confirm the token is shown exactly once, then revoke it.
 *
 * Requires the local API (uvicorn 127.0.0.1:8081, SQLite :memory:, dummy S3
 * creds, AURA_API_ADMIN_PASSWORD=local-smoke-test-password) and the Vite dev
 * server (127.0.0.1:5173). No S3 contact happens: these endpoints only touch the
 * catalogue.
 */

test("create application, space and identity, then revoke", async ({ page }) => {
  const tag = Date.now();
  const appName = `App E2E ${tag}`;
  const spaceName = `espace-e2e-${tag}`;
  const idName = `robot-e2e-${tag}`;

  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page).toHaveURL(/\/admin/);

  const appsSection = page.locator("section", {
    has: page.getByRole("heading", { name: "Applications" }),
  });
  const spacesSection = page.locator("section", {
    has: page.getByRole("heading", { name: "Espaces" }),
  });
  const idsSection = page.locator("section", {
    has: page.getByRole("heading", { name: "Identités machine-à-machine" }),
  });

  await page.getByRole("tab", { name: "Applications et espaces" }).click();

  // 1. Application.
  await appsSection.getByLabel("Nouvelle application").fill(appName);
  await appsSection.getByRole("button", { name: "Créer", exact: true }).click();
  await expect(appsSection.locator("tr", { hasText: appName })).toBeVisible();

  // 2. Space on that application.
  await spacesSection.getByLabel("Application").selectOption({ label: appName });
  await spacesSection.getByLabel("Nom").fill(spaceName);
  await spacesSection.getByRole("button", { name: "Créer l'espace" }).click();
  await expect(spacesSection.locator("tr", { hasText: spaceName })).toBeVisible();

  await page.getByRole("tab", { name: "Identités de service" }).click();

  // 3. Identity: the token must appear exactly once.
  await idsSection.getByLabel("Nom").fill(idName);
  await idsSection
    .getByLabel("Espace")
    .selectOption({ label: `${spaceName} (prod)` });
  await idsSection.getByLabel("objects:write").check();
  await idsSection.getByRole("button", { name: "Créer l'identité" }).click();

  const tokenPanel = page.locator(".token-panel");
  await expect(tokenPanel).toBeVisible();
  await expect(tokenPanel.locator(".token-value")).not.toBeEmpty();
  await tokenPanel.getByRole("button", { name: "J'ai copié le jeton" }).click();
  await expect(tokenPanel).toHaveCount(0);

  // 4. Revoke it.
  const row = idsSection.locator("tr", { hasText: idName });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Révoquer" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Révoquer" })
    .click();
  await expect(row.getByText("Révoquée")).toBeVisible();
});
