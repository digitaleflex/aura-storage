import { test, expect } from "@playwright/test";

/**
 * M04: operational management of applications, spaces and buckets from the
 * console.
 *
 * Requires the local API (uvicorn 127.0.0.1:8082, SQLite :memory:, dummy S3
 * creds, AURA_API_ADMIN_PASSWORD=local-smoke-test-password) and the Vite dev
 * server (127.0.0.1:5174, AURA_API_PROXY=http://127.0.0.1:8082). No S3 contact
 * happens: these endpoints only touch the catalogue.
 */
test("create, rename, deactivate and configure applications, spaces and buckets", async ({
  page,
}) => {
  const tag = Date.now();
  const appName = `App M04 ${tag}`;
  const renamed = `App M04-${tag} v2`;
  const spaceName = `espace-m04-${tag}`;
  const extraBucket = `aura-m04-${tag}`;

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
  const bucketsSection = page.locator("section", {
    has: page.getByRole("heading", { name: "Buckets" }),
  });

  // 1. Application: create, rename, deactivate, reactivate.
  await appsSection.getByLabel("Nouvelle application").fill(appName);
  await appsSection.getByRole("button", { name: "Créer", exact: true }).click();
  await expect(appsSection.locator("tr", { hasText: appName })).toBeVisible();

  const appRow = appsSection.locator("tr", { hasText: appName });
  await appRow.getByRole("button", { name: "Modifier" }).click();
  const appDialog = page.getByRole("dialog");
  await appDialog.getByLabel("Nom", { exact: true }).fill(renamed);
  await appDialog.getByRole("button", { name: "Enregistrer" }).click();

  const renamedRow = appsSection.locator("tr", { hasText: renamed });
  await expect(renamedRow).toBeVisible();

  await renamedRow.getByRole("button", { name: "Désactiver" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Désactiver" })
    .click();
  await expect(renamedRow.getByText("Désactivé")).toBeVisible();

  await renamedRow.getByRole("button", { name: "Activer" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Activer" }).click();
  await expect(renamedRow.getByText("Actif")).toBeVisible();

  // 2. Space: create on that application, then change its environment.
  await spacesSection.getByLabel("Application").selectOption({ label: renamed });
  await spacesSection.getByLabel("Nom", { exact: true }).fill(spaceName);
  await spacesSection.getByRole("button", { name: "Créer l'espace" }).click();
  const spaceRow = spacesSection.locator("tr", { hasText: spaceName });
  await expect(spaceRow).toBeVisible();

  await spaceRow.getByRole("button", { name: "Modifier" }).click();
  const spaceDialog = page.getByRole("dialog");
  await spaceDialog.getByLabel("Environnement").fill("staging");
  await spaceDialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(spaceRow.getByText("staging")).toBeVisible();

  // 3. Buckets: register an extra bucket and make it the default.
  await bucketsSection
    .getByLabel("Espace")
    .selectOption({ label: `${spaceName} (staging)` });
  await bucketsSection.getByLabel("Nom du bucket").fill(extraBucket);
  await bucketsSection
    .getByRole("button", { name: "Enregistrer le bucket" })
    .click();

  const bucketRow = bucketsSection.locator("tr", { hasText: extraBucket });
  await expect(bucketRow).toBeVisible();
  await expect(bucketRow.getByText("Non")).toBeVisible();
  await bucketRow.getByRole("button", { name: "Définir par défaut" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Définir par défaut" })
    .click();
  await expect(bucketRow.getByText("Oui")).toBeVisible();
});
