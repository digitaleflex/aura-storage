import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Saved tags are clickable in the details drawer: clicking one applies the
 * files filter. The API is mocked so the catalogue is never modified.
 */

const FILE = {
  id: "obj-tag-1",
  display_name: "cours.pdf",
  content_type: "application/pdf",
  size_bytes: 12_345,
  status: "available",
  folder_id: null,
  checksum_sha256: "abc123",
  created_at: 1_700_000_000,
  updated_at: 1_700_000_500,
  tags: ["maths", "l1"],
};

async function mockApi(page: Page): Promise<string[]> {
  const queries: string[] = [];
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path === "/api/v1/login") {
      await route.fulfill({ json: { csrf_token: "csrf-test" } });
    } else if (path === "/api/v1/me") {
      await route.fulfill({
        json: {
          id: "u1", kind: "user", name: "admin", role: "admin", space_id: "s1",
          application_id: "a1", scopes: ["objects:read"],
          csrf_token: "csrf-test",
        },
      });
    } else if (path === "/api/v1/folders") {
      await route.fulfill({ json: { items: [] } });
    } else if (path === "/api/v1/objects" && method === "GET") {
      queries.push(url.search);
      await route.fulfill({ json: { items: [FILE] } });
    } else if (path === "/api/v1/objects/tags" && method === "GET") {
      await route.fulfill({
        json: { items: [{ tag: "maths", count: 1 }, { tag: "l1", count: 1 }] },
      });
    } else {
      await route.fulfill({ status: 404, json: { detail: "not mocked" } });
    }
  });
  return queries;
}

test("clicking a saved tag applies the filter and closes the drawer", async ({ page }) => {
  const queries = await mockApi(page);
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();

  await page.getByRole("button", { name: `Détails de ${FILE.display_name}` }).click();
  const panel = page.getByRole("dialog", { name: FILE.display_name });
  await expect(panel).toBeVisible();

  await panel.getByRole("button", { name: "Filtrer par l'étiquette maths" }).click();

  await expect(panel).toBeHidden();
  await expect.poll(() => queries.some((q) => q.includes("tag=maths"))).toBe(true);
  await expect(page.locator('input[name="tag"]')).toHaveValue("maths");
  await expect(page.getByRole("button", { name: /^Filtres/ })).toContainText("1");
});
