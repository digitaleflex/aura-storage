import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Keyboard shortcuts and accessibility polish (UI P1/P2):
 * - `?` opens the shortcut legend, `/` focuses the search field;
 * - `Suppr` asks before deleting a selection even when focus is on a checkbox;
 * - the row menu is usable with Arrow keys and returns focus to its trigger;
 * - the mobile drawer traps Tab focus and restores it on Escape.
 *
 * The API is fully mocked: no object, folder or usage record is created and S3
 * is never contacted.
 */

const OBJECT = {
  id: "obj-1",
  display_name: "rapport.pdf",
  content_type: "application/pdf",
  size_bytes: 1024,
  status: "available",
  folder_id: null,
  checksum_sha256: "a".repeat(64),
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
};

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
          scopes: [
            "objects:read",
            "objects:write",
            "objects:delete",
            "objects:purge",
            "folders:write",
            "admin:read",
            "admin:write",
          ],
          csrf_token: "csrf-test",
        },
      });
    } else if (path === "/api/v1/folders") {
      await route.fulfill({ json: { items: [] } });
    } else if (path === "/api/v1/objects" && method === "GET") {
      await route.fulfill({ json: { items: [OBJECT] } });
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
            objects_by_status: { available: 1 },
            available_count: 1,
            stored_bytes: 1024,
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

test("`?` opens the legend and `/` focuses the search field", async ({ page }) => {
  await setup(page);

  await page.keyboard.press("Shift+/");
  const legend = page.getByRole("dialog", { name: "Raccourcis clavier" });
  await expect(legend).toBeVisible();
  await expect(legend.getByText("Rechercher dans le dossier courant")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(legend).toHaveCount(0);

  await page.keyboard.press("/");
  await expect(page.getByLabel("Rechercher")).toBeFocused();
});

test("Suppr asks for confirmation on a checked selection", async ({ page }) => {
  await setup(page);

  await page.getByLabel("Sélectionner rapport.pdf").check();
  // Focus stays on the checkbox: the shortcut must still fire.
  await page.keyboard.press("Delete");

  const confirm = page.getByRole("dialog", { name: "Supprimer la sélection" });
  await expect(confirm).toBeVisible();
  await expect(confirm.getByText("Marquer")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(confirm).toHaveCount(0);
});

test("the row menu supports Arrow keys and restores focus on Escape", async ({
  page,
}) => {
  await setup(page);

  const trigger = page.getByRole("button", { name: "Actions pour rapport.pdf" });
  await trigger.click();
  const menu = page.getByRole("menu", { name: "Actions pour rapport.pdf" });
  await expect(menu).toBeVisible();
  const items = menu.getByRole("menuitem");
  await expect(items.first()).toBeFocused();

  const firstLabel = await items.first().innerText();
  await page.keyboard.press("ArrowDown");
  await expect(items.nth(1)).toBeFocused();
  await expect(items.nth(1)).not.toHaveText(firstLabel);

  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("the mobile drawer traps focus and returns it to the menu button", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);

  const opener = page.getByRole("button", {
    name: "Ouvrir le menu de navigation",
  });
  await opener.click();
  const drawer = page.getByRole("dialog", { name: "Navigation mobile" });
  await expect(drawer).toBeVisible();
  await expect(
    drawer.getByRole("button", { name: "Fermer le menu" }),
  ).toBeFocused();

  // Tab must keep focus inside the drawer.
  for (let i = 0; i < 8; i += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(
      () =>
        !!document
          .querySelector("#mobile-navigation")
          ?.contains(document.activeElement),
    );
    expect(inside).toBe(true);
  }

  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(opener).toBeFocused();
});
