import { test, expect } from "@playwright/test";

/**
 * Admin "Intégrations": one partner site = metadata + a dedicated service
 * identity. Requires the local API and Vite dev server (same fixture as
 * admin-management.spec.ts). Only the catalogue is touched.
 */
test("create, edit, rotate and revoke a partner integration", async ({ page }) => {
  const tag = Date.now();
  const siteName = `Cours ${tag}`;
  const renamed = `Cours ${tag} v2`;

  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page).toHaveURL(/\/admin/);

  await page.getByRole("tab", { name: "Intégrations" }).click();
  const section = page.locator("section", {
    has: page.getByRole("heading", { name: "Intégrations partenaires" }),
  });

  await section.getByLabel("Nom du site").fill(siteName);
  await section.getByLabel("Origine (https)").fill(`https://cours-${tag}.example.com`);
  await section.getByLabel("Espace").selectOption({ index: 1 });
  await section.getByLabel("TTL média conseillé (secondes)").fill("21600");
  await section.getByRole("button", { name: "Créer le site partenaire" }).click();

  // The one-time token panel appears; the row is listed with an active key.
  await expect(page.getByText("Jeton affiché une seule fois")).toBeVisible();
  const row = section.locator("tr", { hasText: siteName });
  await expect(row).toBeVisible();
  await expect(row.getByText("Clé active")).toBeVisible();
  await expect(row.getByText("6 h")).toBeVisible();

  // Edit the metadata only (the key and the space are fixed).
  await row.getByRole("button", { name: "Modifier" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom du site").fill(renamed);
  await dialog.getByLabel("Notes").fill("Parcours L1");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  const renamedRow = section.locator("tr", { hasText: renamed });
  await expect(renamedRow).toBeVisible();
  await expect(renamedRow.getByText("Parcours L1")).toBeVisible();

  // Rotation shows a fresh token once.
  await renamedRow.getByRole("button", { name: "Rotation" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Rotation" }).click();
  await expect(page.getByText("Jeton affiché une seule fois")).toBeVisible();

  // Revocation flips the row and removes the actions.
  await renamedRow.getByRole("button", { name: "Révoquer" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Révoquer" }).click();
  await expect(renamedRow.getByText("Clé révoquée")).toBeVisible();
  await expect(renamedRow.getByRole("button", { name: "Révoquer" })).toBeDisabled();
});
