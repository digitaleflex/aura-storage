import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * UI v2 shell and Fichiers layout: regressions found by the UI audit.
 *
 * The first two tests use the local API (uvicorn 127.0.0.1:8081, SQLite
 * :memory:, dummy S3 creds, AURA_API_ADMIN_PASSWORD=local-smoke-test-password)
 * and leave the catalogue as they found it. The details-panel test mocks the
 * API so it needs an object row without creating one. Vite serves the SPA on
 * 127.0.0.1:5173. S3 is never contacted.
 */

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

test("the top bar names the signed-in account and its role", async ({ page }) => {
  await login(page);
  const topbar = page.getByRole("banner");
  await expect(topbar.getByText("admin", { exact: true })).toBeVisible();
  await expect(topbar.getByText("Administrateur")).toBeVisible();
});

test("a new folder can be typed straight away and its notice is on screen", async ({
  page,
}) => {
  const name = `Clavier ${Date.now()}`;
  await login(page);

  await page.getByRole("button", { name: "Nouveau dossier" }).click();
  // Focus lands in the name field, not on the dialog's "Fermer" button.
  await expect(page.getByRole("dialog").getByLabel("Nom")).toBeFocused();
  await page.keyboard.type(name);
  await page.keyboard.press("Enter");

  await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  // The confirmation renders under the page title, not below the register.
  await expect(page.getByText("Dossier créé.")).toBeInViewport();

  // Leave the shared catalogue empty for the other suites.
  await page.getByRole("button", { name: `Actions pour le dossier ${name}` }).click();
  await page.getByRole("menuitem", { name: "Supprimer" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Supprimer" }).click();
  await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
});

test("Escape closes the details panel", async ({ page }) => {
  const fileName = "rapport-trimestriel.pdf";
  await page.route("**/api/v1/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/login") {
      await route.fulfill({ json: { csrf_token: "csrf-test" } });
    } else if (path === "/api/v1/me") {
      await route.fulfill({
        json: {
          id: "u1", kind: "user", name: "admin", role: "admin", space_id: "s1",
          application_id: "a1", scopes: ["objects:read"], csrf_token: "csrf-test",
        },
      });
    } else if (path === "/api/v1/folders") {
      await route.fulfill({ json: { items: [] } });
    } else if (path === "/api/v1/objects") {
      await route.fulfill({
        json: {
          items: [{
            id: "obj-1", display_name: fileName, content_type: "application/pdf",
            size_bytes: 11, status: "available", folder_id: null,
            checksum_sha256: "a".repeat(64), created_at: 1_700_000_000,
            updated_at: 1_700_000_000,
          }],
        },
      });
    } else {
      await route.fulfill({ status: 404, json: { detail: "not mocked" } });
    }
  });
  await login(page);

  await page.getByRole("button", { name: `Détails de ${fileName}` }).click();
  const panel = page.getByRole("dialog", { name: fileName });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("button", { name: "Fermer les détails" })).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
});
