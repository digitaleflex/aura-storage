import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Regression guard for the /shares route itself (React error #310).
 *
 * The page used to call useMemo after its `if (loading) return ...` branch, so
 * the first render ran fewer hooks than the second one and React tore the tree
 * down with "Rendered more hooks than during the previous render". Navigating
 * directly to /shares is enough to reproduce it: the loading pass and the
 * loaded pass must both render the page. The API is fully mocked.
 */

function objectItem(id: string, name: string) {
  return {
    id,
    display_name: name,
    content_type: "text/plain",
    size_bytes: 1024,
    status: "available",
    folder_id: null,
    checksum_sha256: "a".repeat(64),
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
  };
}

function folderItem(id: string, name: string) {
  return {
    id,
    name,
    parent_id: null,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
  };
}

async function mockApi(
  page: Page,
  items: ReturnType<typeof objectItem>[],
  folders: ReturnType<typeof folderItem>[],
) {
  // The onboarding tour redirects first-time visitors to /onboarding; these
  // tests target the shares route, so mark it as already seen.
  await page.addInitScript(() => {
    try {
      localStorage.setItem("aura_onboarding_seen", "1");
    } catch {
      /* about:blank has no storage: harmless, the next navigation re-runs this */
    }
  });
  await page.route("**/api/v1/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname;

    if (path === "/api/v1/me") {
      return route.fulfill({
        json: {
          id: "u1",
          kind: "user",
          name: "admin",
          role: "admin",
          space_id: "s1",
          application_id: "a1",
          scopes: ["objects:read", "objects:write"],
          csrf_token: "csrf-test",
        },
      });
    }
    if (path === "/api/v1/objects") {
      return route.fulfill({ json: { items } });
    }
    if (path === "/api/v1/folders") {
      return route.fulfill({ json: { items: folders } });
    }
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
}

test("the shares page renders its resources after loading", async ({ page }) => {
  await mockApi(
    page,
    [objectItem("obj-1", "notes.txt")],
    [folderItem("folder-1", "Docs")],
  );

  await page.goto("/shares");

  await expect(
    page.getByRole("heading", { level: 1, name: "Partages publics" }),
  ).toBeVisible();
  await expect(page.getByText("Ressources (2)")).toBeVisible();
  await expect(page.getByRole("cell", { name: "notes.txt" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Docs" })).toBeVisible();
  // The hook-order crash used to surface this boundary instead of the page.
  await expect(
    page.getByRole("heading", { name: "Cette page n'a pas pu s'afficher" }),
  ).toHaveCount(0);
});

test("the shares page renders its empty state after loading", async ({ page }) => {
  await mockApi(page, [], []);

  await page.goto("/shares");

  await expect(
    page.getByRole("heading", { level: 1, name: "Partages publics" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 2, name: "Aucun fichier ni dossier" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Cette page n'a pas pu s'afficher" }),
  ).toHaveCount(0);
});
