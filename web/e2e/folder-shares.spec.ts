import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Public folder share links. The API is fully mocked: nothing is minted
 * server-side and no request reaches S3. Covers the folder-specific UI:
 * the "Partager" action on a folder, the one-time link, the download-oriented
 * wording, and revocation.
 */

const FOLDER = {
  id: "folder-1",
  owner_id: "u1",
  parent_id: null,
  name: "Documents",
  created_at: Math.floor(Date.now() / 1000) - 60,
};

type MockShare = {
  id: string;
  folder_id: string;
  created_by: string;
  created_by_kind: string;
  created_at: number;
  expires_at: number;
  max_uses: number | null;
  use_count: number;
  last_used_at: number | null;
  revoked_at: number | null;
  active: boolean;
};

async function setup(page: Page, shares: MockShare[]) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();

    if (path === "/api/v1/login") {
      return route.fulfill({ json: { csrf_token: "csrf-test" } });
    }
    if (path === "/api/v1/me") {
      return route.fulfill({
        json: {
          id: "u1", kind: "user", name: "admin", role: "admin", space_id: "s1",
          application_id: "a1", scopes: ["objects:read", "objects:write"],
          csrf_token: "csrf-test",
        },
      });
    }
    if (path === "/api/v1/folders" && method === "GET") {
      return route.fulfill({ json: { items: [FOLDER] } });
    }
    if (path === "/api/v1/objects" && method === "GET") {
      return route.fulfill({ json: { items: [] } });
    }
    if (path === "/api/v1/folders/folder-1/shares" && method === "GET") {
      return route.fulfill({ json: { items: shares } });
    }
    if (path === "/api/v1/folders/folder-1/share" && method === "POST") {
      const body = route.request().postDataJSON() as {
        expires_in: number;
        max_uses: number | null;
      };
      const now = Math.floor(Date.now() / 1000);
      const created: MockShare = {
        id: "share-1", folder_id: "folder-1", created_by: "u1",
        created_by_kind: "user", created_at: now,
        expires_at: now + body.expires_in, max_uses: body.max_uses,
        use_count: 0, last_used_at: null, revoked_at: null, active: true,
      };
      shares.unshift(created);
      return route.fulfill({
        json: {
          id: created.id, folder_id: "folder-1", url: "/f/one-time-token",
          token: "one-time-token", expires_in: body.expires_in,
          expires_at: created.expires_at, max_uses: body.max_uses,
        },
      });
    }
    const revoke = path.match(/^\/api\/v1\/folders\/folder-1\/shares\/([^/]+)$/);
    if (revoke && method === "DELETE") {
      const target = shares.find((s) => s.id === revoke[1]);
      if (target) {
        target.revoked_at = 1_700_000_100;
        target.active = false;
      }
      return route.fulfill({
        json: { id: revoke[1], revoked: true, revoked_at: 1_700_000_100 },
      });
    }
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });

  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("x");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

async function openFolderShare(page: Page) {
  await page
    .getByRole("button", { name: "Actions pour le dossier Documents" })
    .click();
  await page.getByRole("menuitem", { name: "Partager" }).click();
  return page.getByRole("dialog", { name: /Partager — Documents/ });
}

test("creating a folder link shows the one-time URL", async ({ page }) => {
  const shares: MockShare[] = [];
  await setup(page, shares);
  const dialog = await openFolderShare(page);

  // A folder link has no per-link "opening mode": each file decides safely.
  await expect(dialog.getByLabel("À l'ouverture")).toHaveCount(0);
  await expect(dialog.getByLabel("Téléchargements maximum")).toBeVisible();

  await dialog.getByRole("button", { name: "Créer le lien" }).click();

  await expect(dialog.getByLabel("Lien de partage")).toHaveValue(
    /\/f\/one-time-token$/,
  );
  await expect(dialog.getByText("il ne sera plus affiché")).toBeVisible();
  await expect(dialog.getByText("Actif")).toBeVisible();
  await expect(dialog.getByText(/Dossier · 0 téléchargement/)).toBeVisible();
});

test("a folder link can be revoked after confirmation", async ({ page }) => {
  const shares: MockShare[] = [{
    id: "share-1", folder_id: "folder-1", created_by: "u1",
    created_by_kind: "user", created_at: Math.floor(Date.now() / 1000) - 60,
    expires_at: Math.floor(Date.now() / 1000) + 30 * 86_400, max_uses: null, use_count: 0,
    last_used_at: null, revoked_at: null, active: true,
  }];
  await setup(page, shares);
  const dialog = await openFolderShare(page);

  await dialog.getByRole("button", { name: "Révoquer" }).click();
  await expect(dialog.getByText("Révoquer ce lien ?")).toBeVisible();
  await dialog.getByRole("button", { name: "Confirmer" }).click();

  await expect(dialog.getByText("Révoqué")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Révoquer" })).toHaveCount(0);
});
