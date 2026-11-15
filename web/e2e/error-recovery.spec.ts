import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Error handling must never strand the user: a crashing page keeps the shell
 * (sidebar, top bar) alive, and every error screen offers a way out — retry,
 * back, the files page, or any other page from the menu — without a full
 * reload.
 */

type Mocks = {
  /** Objects answer is malformed: the shares page throws while rendering. */
  brokenShares: boolean;
};

async function mockApi(page: Page, mocks: Mocks) {
  // The onboarding tour redirects first-time visitors to /onboarding; these
  // tests exercise error recovery, so mark it as already seen.
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
          role: "user",
          space_id: "s1",
          application_id: "a1",
          scopes: ["objects:read", "objects:write"],
          csrf_token: "csrf-test",
        },
      });
    }
    if (path === "/api/v1/objects") {
      return route.fulfill({ json: { items: mocks.brokenShares ? null : [] } });
    }
    if (path === "/api/v1/folders") {
      return route.fulfill({ json: { items: [] } });
    }
    return route.fulfill({ json: { items: [] } });
  });
}

test("a crashing page keeps the shell and Retour goes back", async ({ page }) => {
  const mocks: Mocks = { brokenShares: true };
  await mockApi(page, mocks);

  await page.goto("/help");
  await expect(page.getByRole("heading", { level: 1, name: /Aide/ })).toBeVisible();

  await page.getByRole("link", { name: "Partages" }).click();

  // The page failed, but the navigation is still there: nothing is stranded.
  await expect(
    page.getByRole("heading", { name: "Cette page n'a pas pu s'afficher" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Aide" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Partages" })).toBeVisible();

  // "Retour" is a real history move, not a reload: we land back on Aide.
  await page.getByRole("button", { name: "Retour", exact: true }).click();
  await expect(page).toHaveURL(/\/help$/);
  await expect(page.getByRole("heading", { level: 1, name: /Aide/ })).toBeVisible();
});

test("another page opens from the menu while the error screen is shown", async ({ page }) => {
  const mocks: Mocks = { brokenShares: true };
  await mockApi(page, mocks);

  await page.goto("/help");
  await page.getByRole("link", { name: "Partages" }).click();
  await expect(
    page.getByRole("heading", { name: "Cette page n'a pas pu s'afficher" }),
  ).toBeVisible();

  // The shell is outside the failing subtree: choosing another page recovers
  // without reloading, and the error is cleared by the new location.
  await page.getByRole("link", { name: "Aide" }).click();
  await expect(page).toHaveURL(/\/help$/);
  await expect(page.getByRole("heading", { level: 1, name: /Aide/ })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Cette page n'a pas pu s'afficher" }),
  ).toHaveCount(0);
});

test("Réessayer recovers once the page can render again", async ({ page }) => {
  const mocks: Mocks = { brokenShares: true };
  await mockApi(page, mocks);

  await page.goto("/help");
  await page.getByRole("link", { name: "Partages" }).click();
  await expect(
    page.getByRole("heading", { name: "Cette page n'a pas pu s'afficher" }),
  ).toBeVisible();

  mocks.brokenShares = false;
  await page.getByRole("button", { name: "Réessayer", exact: true }).click();

  // Same URL, successful render: the retry did not navigate away.
  await expect(page).toHaveURL(/\/shares$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Partages publics" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Cette page n'a pas pu s'afficher" }),
  ).toHaveCount(0);
});

test("an unknown URL is not a dead end", async ({ page }) => {
  await mockApi(page, { brokenShares: false });

  await page.goto("/cette-page-nexiste-pas");
  await expect(
    page.getByRole("heading", { name: "Cette page n'existe pas" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Aller aux fichiers" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
});
