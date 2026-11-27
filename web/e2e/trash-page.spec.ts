import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/** Trash page permissions and irreversible purge confirmation (mocked API). */

const trashed = {
  id: "t1",
  display_name: "rapport.txt",
  content_type: "text/plain",
  size_bytes: 12,
  status: "deleted",
  folder_id: null,
  checksum_sha256: "a".repeat(64),
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
};

async function setup(page: Page, scopes: string[], purged: string[]) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/login") {
      await route.fulfill({ json: { csrf_token: "csrf-test" } });
    } else if (path === "/api/v1/me") {
      await route.fulfill({
        json: {
          id: "u1",
          kind: "user",
          name: "admin",
          role: "admin",
          space_id: "s1",
          application_id: "a1",
          scopes,
          csrf_token: "csrf-test",
        },
      });
    } else if (path === "/api/v1/objects") {
      await route.fulfill({ json: { items: [trashed] } });
    } else if (path === "/api/v1/objects/t1/purge") {
      purged.push("t1");
      await route.fulfill({ json: { id: "t1", status: "purged" } });
    } else {
      await route.fulfill({ status: 404, json: { detail: "not mocked" } });
    }
  });

  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("x");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.goto("/trash");
  await expect(page.getByRole("heading", { level: 1, name: "Corbeille" })).toBeVisible();
}

test("a user without objects:purge never sees the purge action", async ({ page }) => {
  await setup(page, ["objects:read", "objects:delete"], []);
  await expect(page.getByText("rapport.txt", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Purger définitivement/ })).toHaveCount(0);
});

test("purge requires confirmation and removes the row only after approval", async ({ page }) => {
  const purged: string[] = [];
  await setup(page, ["objects:read", "objects:delete", "objects:purge"], purged);

  await page.getByRole("button", { name: "Purger définitivement rapport.txt" }).click();
  const dialog = page.getByRole("dialog", { name: "Purger définitivement" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Annuler" }).click();
  expect(purged).toEqual([]);

  await page.getByRole("button", { name: "Purger définitivement rapport.txt" }).click();
  await page
    .getByRole("dialog", { name: "Purger définitivement" })
    .getByRole("button", { name: "Purger définitivement" })
    .click();

  await expect(page.getByText("rapport.txt", { exact: true })).toHaveCount(0);
  expect(purged).toEqual(["t1"]);
});
