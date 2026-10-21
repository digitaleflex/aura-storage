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
