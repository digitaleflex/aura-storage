import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

/**
 * Administration tabs and the audit log's readable actors.
 *
 * Requires the local API (uvicorn 127.0.0.1:8081, SQLite :memory:, dummy S3
 * creds, AURA_API_ADMIN_PASSWORD=local-smoke-test-password) and the Vite dev
 * server (127.0.0.1:5173). Only the catalogue is touched; S3 is never contacted.
 */

async function loginToAdmin(page: Page, hash = "") {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page).toHaveURL(/\/admin/);
  if (hash) {
    await page.goto(`/admin#${hash}`);
  }
}

test("tabs switch sections and follow the arrow keys", async ({ page }) => {
  await loginToAdmin(page);

  const overview = page.getByRole("tab", { name: "Vue d'ensemble" });
  await expect(overview).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Couvertures" })).toBeVisible();
  // Other sections are not on the page until their tab is chosen.
  await expect(page.getByRole("heading", { name: "Journal d'audit" })).toBeHidden();

  await overview.focus();
  await page.keyboard.press("ArrowRight");
  const audit = page.getByRole("tab", { name: "Journal d'audit" });
  await expect(audit).toHaveAttribute("aria-selected", "true");
  await expect(audit).toBeFocused();
  await expect(page.getByRole("heading", { name: "Journal d'audit" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeHidden();
});

test("a link with #audit opens the audit tab and names the signed-in account", async ({
  page,
}) => {
  await loginToAdmin(page, "audit");

  await expect(page.getByRole("tab", { name: "Journal d'audit" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  // The login event's actor is the signed-in account, shown by name.
  await expect(page.getByRole("table").getByText("admin", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("table").getByText("Réussi").first()).toBeVisible();
});

test("the sidebar opens the dedicated cover validation page", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.getByRole("link", { name: "Couvertures" }).click();
  await expect(page).toHaveURL(/\/admin\/covers/);
  await expect(page.getByRole("heading", { level: 1, name: "Validation des couvertures" })).toBeVisible();
});

test("a link with #covers opens the cover validation tab", async ({ page }) => {
  await loginToAdmin(page, "covers");

  const covers = page.getByRole("tab", { name: "Couvertures" });
  await expect(covers).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { level: 2, name: "Validation des couvertures" })).toBeVisible();
});

test("the cover validation page offers a cover search for each book", async ({ page }) => {
  // One deterministic book: the button is per book, so the catalogue need not
  // contain a prepared cover review for this assertion.
  await page.route("**/api/v1/admin/cover-candidates", (route) =>
    route.fulfill({
      json: {
        generated_at: 1_700_000_000,
        counts: { books: 1, with_candidates: 0, candidates: 0 },
        books: [
          {
            object_id: "00000000-0000-0000-0000-000000000001",
            title: "Livre témoin",
            author: "Auteur témoin",
            display_name: "livre-temoine.mp3",
            status: "pending",
            chosen_url: null,
            cover_url: null,
            candidates: [],
          },
        ],
      },
    }),
  );

  await loginToAdmin(page);
  await page.getByRole("link", { name: "Couvertures" }).click();
  await expect(page).toHaveURL(/\/admin\/covers/);
  await expect(page.getByRole("heading", { level: 1, name: "Validation des couvertures" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Rechercher une couverture" })).toBeVisible();
});
