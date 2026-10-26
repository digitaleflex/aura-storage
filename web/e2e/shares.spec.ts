import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Public share links. The API is fully mocked: nothing is minted server-side
 * and no request ever reaches S3. Covers the three user-visible moments:
 * creating a one-time link, seeing it listed as active, revoking it.
 */

function item(id: string, name: string, type: string) {
  return {
    id, display_name: name, content_type: type, size_bytes: 2048,
    status: "available", folder_id: null,
    checksum_sha256: "a".repeat(64), created_at: 1_700_000_000, updated_at: 1_700_000_000,
  };
}

const ITEMS = [item("obj-1", "notes.txt", "text/plain")];

type MockShare = {
  id: string;
  object_id: string;
  created_by: string;
  created_by_kind: string;
  content_disposition: "attachment" | "inline";
  created_at: number;
  expires_at: number;
  max_uses: number | null;
  use_count: number;
  last_used_at: number | null;
  revoked_at: number | null;
  active: boolean;
};

async function setup(page: Page, shares: MockShare[], items = ITEMS) {
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
    if (path === "/api/v1/folders") {
      return route.fulfill({ json: { items: [] } });
    }
    if (path === "/api/v1/objects" && method === "GET") {
      return route.fulfill({ json: { items } });
    }
    if (path === "/api/v1/objects/obj-1/shares" && method === "GET") {
      return route.fulfill({ json: { items: shares } });
    }
    if (path === "/api/v1/objects/obj-1/share" && method === "POST") {
      const body = route.request().postDataJSON() as {
        expires_in: number;
        max_uses: number | null;
        content_disposition: "attachment" | "inline";
      };
      const now = 1_700_000_000;
      const created: MockShare = {
        id: "share-1", object_id: "obj-1", created_by: "u1",
        created_by_kind: "user", content_disposition: body.content_disposition,
        created_at: now, expires_at: now + body.expires_in,
        max_uses: body.max_uses, use_count: 0, last_used_at: null,
        revoked_at: null, active: true,
      };
      shares.unshift(created);
      return route.fulfill({
        json: {
          id: created.id, object_id: "obj-1", url: "/s/one-time-token",
          token: "one-time-token", expires_in: body.expires_in,
          expires_at: created.expires_at, max_uses: body.max_uses,
          content_disposition: body.content_disposition,
        },
      });
    }
    const revoke = path.match(/^\/api\/v1\/objects\/obj-1\/shares\/([^/]+)$/);
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

async function openShare(page: Page) {
  await page.getByRole("button", { name: "Actions pour notes.txt" }).click();
  await page.getByRole("menuitem", { name: "Partager" }).click();
  return page.getByRole("dialog", { name: /Partager — notes\.txt/ });
}

test("creating a link shows the one-time URL", async ({ page }) => {
  const shares: MockShare[] = [];
  await setup(page, shares);
  const dialog = await openShare(page);

  await dialog.getByLabel("Durée").selectOption("86400");
  await dialog.getByRole("button", { name: "Créer le lien" }).click();

  await expect(dialog.getByLabel("Lien de partage")).toHaveValue(
    /\/s\/one-time-token$/,
  );
  await expect(dialog.getByText("il ne sera plus affiché")).toBeVisible();
  await expect(dialog.getByText("Actif")).toBeVisible();
});

test("a link can be revoked after an explicit confirmation", async ({ page }) => {
  const shares: MockShare[] = [{
    id: "share-1", object_id: "obj-1", created_by: "u1", created_by_kind: "user",
    content_disposition: "attachment", created_at: 1_700_000_000,
    expires_at: 1_800_000_000, max_uses: null, use_count: 0,
    last_used_at: null, revoked_at: null, active: true,
  }];
  await setup(page, shares);
  const dialog = await openShare(page);

  await dialog.getByRole("button", { name: "Révoquer" }).click();
  await expect(dialog.getByText("Révoquer ce lien ?")).toBeVisible();
  await dialog.getByRole("button", { name: "Confirmer" }).click();

  await expect(dialog.getByText("Révoqué")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Révoquer" })).toHaveCount(0);
});

test("an active document is shared as a download only", async ({ page }) => {
  // HTML cannot render inline on a share (it could execute on the storage
  // origin), so the browser-render option must not be offered.
  const shares: MockShare[] = [];
  await setup(page, shares, [item("html-1", "page.html", "text/html")]);
  await page.getByRole("button", { name: "Actions pour page.html" }).click();
  await page.getByRole("menuitem", { name: "Partager" }).click();
  const dialog = page.getByRole("dialog", { name: /Partager — page\.html/ });
  const mode = dialog.getByLabel("À l'ouverture");
  await expect(mode.locator("option")).toHaveCount(1);
  await expect(mode).toHaveValue("attachment");
});

test("a video offers inline playback for embedding", async ({ page }) => {
  const shares: MockShare[] = [];
  await setup(page, shares, [item("vid-1", "clip.mp4", "video/mp4")]);
  await page.getByRole("button", { name: "Actions pour clip.mp4" }).click();
  await page.getByRole("menuitem", { name: "Partager" }).click();
  const dialog = page.getByRole("dialog", { name: /Partager — clip\.mp4/ });
  const mode = dialog.getByLabel("À l'ouverture");
  await expect(mode.locator("option")).toHaveCount(2);
  await mode.selectOption("inline");
  await expect(mode).toHaveValue("inline");
});
