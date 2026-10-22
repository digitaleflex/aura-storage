import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Repli de la barre latérale (bug P0).
 *
 * Le paramètre d'état `sidebar` était écrit dans l'URL sous forme de chaîne.
 * Le routeur attend un objet : la chaîne était sérialisée caractère par
 * caractère (`?0=s&1=i&2=d…`), donc `sidebar` ne revenait jamais et la barre
 * ne se repliait pas. Ces tests verrouillent l'écriture (URL propre, une
 * seule clé `sidebar=collapsed`), l'effet visible (rail étroit) et le fait que
 * le masquage des libellés ne supprime pas les noms accessibles.
 *
 * L'API est entièrement mockée : aucun objet, dossier ou relevé de
 * consommation n'est créé et S3 n'est jamais contacté.
 */

async function setup(page: Page) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
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
          scopes: ["objects:read", "admin:read"],
          csrf_token: "csrf-test",
        },
      });
    } else if (path === "/api/v1/folders") {
      await route.fulfill({ json: { items: [] } });
    } else if (path === "/api/v1/objects" && method === "GET") {
      await route.fulfill({ json: { items: [] } });
    } else if (path === "/api/v1/admin/usage") {
      await route.fulfill({
        json: {
          measured_at: 1_700_000_000,
          limits: {
            max_object_bytes: 10_000_000,
            max_pending_intents: 10,
            intent_ttl: 900,
            allow_empty_objects: false,
          },
          totals: {
            objects_by_status: { available: 0 },
            available_count: 0,
            stored_bytes: 0,
          },
          spaces: [],
        },
      });
    } else {
      await route.fulfill({ status: 404, json: { detail: "not mocked" } });
    }
  });

  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Mes fichiers" }),
  ).toBeVisible();
}

test("le bouton de repli écrit `sidebar=collapsed` et replie la barre", async ({
  page,
}) => {
  // Au-delà de 1024 px : le rail manuel a du sens (en dessous, la barre est
  // déjà forcée en icônes par la requête tablette).
  await page.setViewportSize({ width: 1440, height: 900 });
  await setup(page);

  const sidebar = page.locator("aside.sidebar");
  // Le libellé du bouton alterne (« Réduire » / « Agrandir ») : on l'atteint
  // par sa classe pour suivre le même bouton d'un état à l'autre.
  const toggle = page.locator("button.topbar-sidebar-toggle");

  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(toggle).toHaveAccessibleName("Réduire la sidebar");
  await expect(sidebar).not.toHaveClass(/sidebar-collapsed/);

  await toggle.click();

  // L'URL porte l'état… et n'est pas la chaîne sérialisée caractère par
  // caractère que produisait la version buguée (`?0=s&1=i&2=d…`).
  await expect(page).toHaveURL(/[?&]sidebar=collapsed/);
  expect(page.url()).not.toMatch(/[?&]\d+=/);

  // La barre est réellement repliée, pas seulement marquée.
  await expect(sidebar).toHaveClass(/sidebar-collapsed/);
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(toggle).toHaveAccessibleName("Agrandir la sidebar");

  await expect
    .poll(async () => sidebar.evaluate((el) => el.getBoundingClientRect().width))
    .toBeLessThanOrEqual(60);
});

test("replier la barre ne supprime aucun nom accessible", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await setup(page);

  await page.getByRole("button", { name: "Réduire la sidebar" }).click();
  await expect(page.locator("aside.sidebar")).toHaveClass(/sidebar-collapsed/);

  // Les libellés sont masqués visuellement (taille nulle), pas retirés : les
  // liens de navigation restent nommés.
  const filesLink = page.getByRole("link", { name: "Fichiers", exact: true });
  await expect(filesLink).toBeVisible();
  await expect(filesLink).toHaveCSS("font-size", "0px");
  // La marque garde son nom, elle aussi.
  await expect(
    page.getByRole("link", { name: /AURA Vault/ }),
  ).toBeVisible();
});

test("déplier la barre retire la clé `sidebar` de l'URL", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await setup(page);

  const toggle = page.locator("button.topbar-sidebar-toggle");
  await toggle.click();
  await expect(page).toHaveURL(/[?&]sidebar=collapsed/);

  // Convention : `?sidebar=collapsed` matérialise le repli, l'absence de la
  // clé vaut l'état par défaut. On n'écrit jamais `?sidebar=expanded`.
  await toggle.click();
  await expect(page).not.toHaveURL(/[?&]sidebar=/);
  await expect(page.locator("aside.sidebar")).not.toHaveClass(
    /sidebar-collapsed/,
  );
});
