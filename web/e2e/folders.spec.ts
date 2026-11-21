import { test, expect } from "@playwright/test";

/**
 * Logical folders (#62): the "Fichiers" workspace drives the real folder API.
 *
 * Requires the local API (uvicorn 127.0.0.1:8081, SQLite :memory:, dummy S3
 * creds, AURA_API_ADMIN_PASSWORD=local-smoke-test-password) and the Vite dev
 * server (127.0.0.1:5173). Folder CRUD never contacts S3; no object is uploaded.
 *
 * Selectors are role- and label-based on purpose: the folder list markup is a
 * presentation detail and has changed once already, while the accessible names
 * ("Actions pour le dossier <nom>") are the interface the user actually gets.
 */

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

async function createFolder(page: import("@playwright/test").Page, name: string) {
  await page.getByRole("button", { name: "Nouveau dossier" }).click();
  await page.getByRole("dialog").getByLabel("Nom").fill(name);
  await page.getByRole("dialog").getByRole("button", { name: "Créer" }).click();
  await expect(
    page.getByRole("button", { name, exact: true }),
  ).toBeVisible();
}

test("create, rename, open and delete a folder", async ({ page }) => {
  const name = `Dossier E2E ${Date.now()}`;
  const renamed = `${name} renomme`;

  // A folder is reachable by its own name (the open control) and by the label
  // of its row menu; neither depends on a CSS class.
  const open = (label: string) =>
    page.getByRole("button", { name: label, exact: true });
  const actions = (label: string) =>
    page.getByRole("button", { name: `Actions pour le dossier ${label}` });

  await login(page);

  // Create at the root.
  await page.getByRole("button", { name: "Nouveau dossier" }).click();
  await page.getByRole("dialog").getByLabel("Nom").fill(name);
  await page.getByRole("dialog").getByRole("button", { name: "Créer" }).click();
  await expect(open(name)).toBeVisible();

  // Rename it, from the root listing (folder actions live in the row menu).
  await actions(name).click();
  await page.getByRole("menuitem", { name: "Renommer" }).click();
  await page.getByRole("dialog").getByLabel("Nom").fill(renamed);
  await page.getByRole("dialog").getByRole("button", { name: "Renommer" }).click();
  await expect(open(renamed)).toBeVisible();

  // Open it: the page title now names that folder.
  await open(renamed).click();
  await expect(
    page.getByRole("heading", { level: 1, name: renamed }),
  ).toBeVisible();

  // Back to the root via the breadcrumb.
  await page
    .getByRole("navigation", { name: "Fil d'Ariane" })
    .getByRole("button", { name: "Mes fichiers" })
    .click();
  await expect(open(renamed)).toBeVisible();

  // Delete it (empty -> allowed), confirming in the dialog.
  await actions(renamed).click();
  await page.getByRole("menuitem", { name: "Supprimer" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Supprimer" })
    .click();
  await expect(open(renamed)).toHaveCount(0);
});

test("selects several folders and deletes them with their content flow", async ({
  page,
}) => {
  const stamp = Date.now();
  const names = [`Bulk A ${stamp}`, `Bulk B ${stamp}`];

  await login(page);
  for (const name of names) await createFolder(page, name);

  // The unified selection bar counts folders, not only files.
  for (const name of names) {
    await page.getByLabel(`Sélectionner le dossier ${name}`).check();
  }
  await expect(page.getByText("2 dossiers sélectionnés")).toBeVisible();

  await page
    .getByRole("button", { name: /Supprimer la sélection/ })
    .click();

  // Folders route through the recursive confirmation, never the single-file
  // dialog: the typed word is SUPPRIMER for a multi-folder selection.
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Supprimer la sélection et son contenu" }),
  ).toBeVisible();
  await dialog.getByLabel("Confirmation par recopie du nom").fill("SUPPRIMER");
  await dialog
    .getByRole("button", { name: "Supprimer la sélection et son contenu" })
    .click();

  for (const name of names) {
    await expect(
      page.getByRole("button", { name, exact: true }),
    ).toHaveCount(0);
  }
});

test("grid view shows folders with a selection checkbox and their size", async ({
  page,
}) => {
  const name = `Grille E2E ${Date.now()}`;
  await login(page);
  await createFolder(page, name);

  await page.getByRole("button", { name: "Grille", exact: true }).click();

  const card = page.getByRole("listitem").filter({ hasText: name });
  await expect(
    card.getByRole("checkbox", { name: `Sélectionner le dossier ${name}` }),
  ).toBeVisible();
  await expect(card.getByText(/^Dossier · /)).toBeVisible();
  // 0 o comes from the real recursive folder size, never a placeholder.
  await expect(card.getByText("Dossier · 0 o")).toBeVisible();
});
