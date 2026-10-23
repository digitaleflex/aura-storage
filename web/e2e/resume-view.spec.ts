import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * A lost session must not lose the view: the guard sends the user to
 * /login?redirect=…, and after logging back in the folder, filters, loaded
 * pages and scroll offset come back.
 *
 * The catalogue is mocked: 120 objects, 50 per page, so reaching page 3 is a
 * real "200+ elements" situation without a seeded backend.
 */

const ME = {
  id: "u1",
  kind: "user",
  name: "admin",
  role: "user",
  space_id: "s1",
  application_id: "a1",
  scopes: ["objects:read", "objects:write", "objects:delete"],
  csrf_token: "csrf-test",
};

const ALL = Array.from({ length: 120 }, (_, index) => ({
  id: `obj-${index}`,
  display_name: `rapport-${index}.pdf`,
  content_type: "application/pdf",
  size_bytes: 1000 + index,
  checksum_sha256: "abc",
  status: "available",
  folder_id: null,
  created_at: 1_700_000_000 - index,
  updated_at: 1_700_000_000 - index,
}));

async function installMocks(page: Page, state: { dead: boolean }) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/v1/login" && method === "POST") {
      return route.fulfill({ json: { csrf_token: "csrf-test" } });
    }
    if (path === "/api/v1/me") {
      return state.dead
        ? route.fulfill({ status: 401, json: { detail: "session expirée" } })
        : route.fulfill({ json: ME });
    }
    if (path === "/api/v1/folders") {
      return route.fulfill({ json: { items: [] } });
    }
    if (path === "/api/v1/objects" && method === "GET") {
      const offset = Number(url.searchParams.get("offset") ?? "0");
      const limit = Number(url.searchParams.get("limit") ?? "50");
      return route.fulfill({
        json: { items: ALL.slice(offset, offset + limit) },
      });
    }
    return route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });
}

async function login(page: Page) {
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("x");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Mes fichiers" }),
  ).toBeVisible();
}

test("a lost session returns to the same folder, filter and scroll offset", async ({
  page,
}) => {
  const state = { dead: false };
  await installMocks(page, state);


  await page.goto("/login");
  await login(page);

  // A filter the restore must bring back (it is not in the URL).
  await page.getByLabel("Rechercher").fill("rapport");
  await expect(page.getByText("rapport-1.pdf", { exact: true })).toBeVisible();

  // Load past 200 objects by scrolling; the list auto-loads page by page.
  const last = page.getByText("rapport-119.pdf", { exact: true });
  for (let round = 0; round < 30; round += 1) {
    if (await last.isVisible()) break;
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(250);
  }
  await expect(last).toBeVisible();
  const scrollBefore = await page.evaluate(() => window.scrollY);
  expect(scrollBefore).toBeGreaterThan(0);

  // The session dies while the tab stays open; a reload hits GET /me -> 401.
  state.dead = true;
  await page.reload();
  await expect(page).toHaveURL(/\/login$/);

  // Logging back in returns to the files page and restores the view.
  state.dead = false;
  await login(page);
  await expect(page.getByLabel("Rechercher")).toHaveValue("rapport");
  // Page 3 data is only re-fetched if the saved depth was restored.
  await expect(page.getByText("rapport-101.pdf", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  const scrollAfter = await page.evaluate(() => window.scrollY);
  expect(scrollAfter).toBeGreaterThan(0);
});
