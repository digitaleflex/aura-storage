import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

/** « Portail public » card of the admin overview: aggregate listening figures. */

async function loginToAdmin(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page).toHaveURL(/\/admin/);
}

test("the portal card shows the real aggregate figures of the local API", async ({ page }) => {
  await loginToAdmin(page);
  const card = page.getByTestId("portal-stats");
  await expect(card).toBeVisible();
  await expect(card.getByRole("heading", { name: "Portail public" })).toBeVisible();
  await expect(card).toContainText("Comptes visiteurs");
  await expect(card).toContainText("Livres publiés");
});

test("books are ranked with their completion rate and favourites", async ({ page }) => {
  await page.route("**/api/v1/admin/portal-stats", (route) =>
    route.fulfill({
      json: {
        measured_at: 1_790_000_000,
        period: "2026-11",
        totals: { accounts: 12, published_books: 2, listeners: 9, completed: 3, favorites: 5, views_month: 40 },
        books: [
          { id: "a", title: "Germinal", author: "Zola", listeners: 8, completed: 3, completion_rate: 0.375, favorites: 4, views_month: 30 },
          { id: "b", title: "Nana", author: "", listeners: 0, completed: 0, completion_rate: 0, favorites: 1, views_month: 10 },
        ],
      },
    }),
  );
  await loginToAdmin(page);
  const card = page.getByTestId("portal-stats");
  await expect(card.getByText("12", { exact: true })).toBeVisible();
  const first = card.getByRole("row").filter({ hasText: "Germinal" });
  await expect(first).toContainText("Zola");
  await expect(first).toContainText("38 %");
  const second = card.getByRole("row").filter({ hasText: "Nana" });
  await expect(second).toContainText("—"); // no listener -> no completion rate
});

test("an unavailable portal endpoint never disturbs the rest of the overview", async ({ page }) => {
  await page.route("**/api/v1/admin/portal-stats", (route) => route.fulfill({ status: 500, json: { detail: "boom" } }));
  await loginToAdmin(page);
  await expect(page.getByRole("heading", { name: "Consommation" })).toBeVisible();
  await expect(page.getByTestId("portal-stats")).toHaveCount(0);
});
