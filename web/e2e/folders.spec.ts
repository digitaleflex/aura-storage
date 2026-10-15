import { test, expect } from "@playwright/test";

/**
 * Logical folders (#62): the "Fichiers" workspace drives the real folder API.
 *
 * Requires the local API (uvicorn 127.0.0.1:8081, SQLite :memory:, dummy S3
 * creds, AURA_API_ADMIN_PASSWORD=local-smoke-test-password) and the Vite dev
 * server (127.0.0.1:5173). Folder CRUD never contacts S3; no object is uploaded.
 */

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fichiers" })).toBeVisible();
}

test("create, rename, open and delete a folder", async ({ page }) => {
  const name = `Dossier E2E ${Date.now()}`;
  const renamed = `${name} renomme`;

  await login(page);

  // Create at the root.
  await page.getByRole("button", { name: "Nouveau dossier" }).click();
  await page.getByRole("dialog").getByLabel("Nom").fill(name);
  await page.getByRole("dialog").getByRole("button", { name: "Créer" }).click();
  await expect(page.locator(".folder-card", { hasText: name })).toBeVisible();

  // Rename it, from the root listing.
  await page
    .locator(".folder-card", { hasText: name })
    .getByRole("button", { name: "Renommer" })
    .click();
  await page.getByRole("dialog").getByLabel("Nom").fill(renamed);
  await page.getByRole("dialog").getByRole("button", { name: "Renommer" }).click();
  await expect(page.locator(".folder-card", { hasText: renamed })).toBeVisible();

  // Open it: the object panel now targets that folder.
  await page
    .locator(".folder-card", { hasText: renamed })
    .getByRole("button", { name: renamed })
    .click();
  await expect(
    page.getByRole("heading", { name: new RegExp(`Objets — ${renamed}`) }),
  ).toBeVisible();

  // Back to the root via the breadcrumb.
  await page.getByRole("button", { name: "Racine" }).click();
  const card = page.locator(".folder-card", { hasText: renamed });
  await expect(card).toBeVisible();

  // Delete it (empty -> allowed), confirming in the dialog.
  await card.getByRole("button", { name: "Supprimer" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Supprimer" })
    .click();
  await expect(page.locator(".folder-card", { hasText: renamed })).toHaveCount(0);
});
