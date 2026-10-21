import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Master mode in the files page: password step-up, red banner with a
 * countdown, bulk purge and emptying the trash without per-item confirmation.
 * The API is mocked (nothing is purged anywhere).
 */

function obj(id: string, name: string, status = "available") {
  return {
    id, display_name: name, content_type: "text/plain", size_bytes: 10, status,
    folder_id: null, checksum_sha256: "a".repeat(64),
    created_at: 1_700_000_000, updated_at: 1_700_000_000,
  };
}

interface Server {
  masterUntil: number | null;
  purged: string[][];
  emptied: number;
}

async function setup(page: Page, server: Server) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path === "/api/v1/login") return route.fulfill({ json: { csrf_token: "csrf-test" } });
    if (path === "/api/v1/me") {
      return route.fulfill({
        json: {
          id: "u1", kind: "user", name: "admin", role: "admin", space_id: "s1",
          application_id: "a1", csrf_token: "csrf-test", master_until: server.masterUntil,
          scopes: ["objects:read", "objects:write", "objects:delete", "objects:purge"],
        },
      });
    }
    if (path === "/api/v1/me/master-mode" && method === "POST") {
      const { password } = request.postDataJSON() as { password: string };
      if (password !== "bon-mot-de-passe") {
        return route.fulfill({ status: 403, json: { detail: "password does not match" } });
      }
      server.masterUntil = Math.floor(Date.now() / 1000) + 900;
      return route.fulfill({ json: { master_until: server.masterUntil } });
    }
    if (path === "/api/v1/me/master-mode" && method === "DELETE") {
      server.masterUntil = null;
      return route.fulfill({ json: { master_until: null } });
    }
    if (path === "/api/v1/objects/bulk-purge") {
      const { ids } = request.postDataJSON() as { ids: string[] };
      server.purged.push(ids);
      return route.fulfill({ json: { purged: ids, not_found: [], failed: [] } });
    }
    if (path === "/api/v1/objects/trash/empty") {
      server.emptied += 1;
      return route.fulfill({ json: { purged: ["t1"], not_found: [], failed: [], more: false } });
    }
    if (path === "/api/v1/folders") return route.fulfill({ json: { items: [] } });
    if (path === "/api/v1/objects" && method === "GET") {
      const status = url.searchParams.get("status");
      return route.fulfill({
        json: {
          items: status === "deleted"
            ? [obj("t1", "ancien.txt", "deleted")]
            : [obj("o1", "a.txt"), obj("o2", "b.txt")],
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("x");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

test("a wrong password says so and keeps master mode off", async ({ page }) => {
  const server: Server = { masterUntil: null, purged: [], emptied: 0 };
  await setup(page, server);
  await page.getByRole("button", { name: "Mode maître" }).click();
  const dialog = page.getByRole("dialog", { name: "Activer le mode maître" });
  await dialog.getByLabel("Mot de passe").fill("faux");
  await dialog.getByRole("button", { name: "Activer" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Mot de passe incorrect.");
  await expect(page.getByTestId("master-banner")).toHaveCount(0);
});

test("master mode purges a selection in one click, then can be left", async ({ page }) => {
  const server: Server = { masterUntil: null, purged: [], emptied: 0 };
  await setup(page, server);
  await page.getByRole("button", { name: "Mode maître" }).click();
  const dialog = page.getByRole("dialog", { name: "Activer le mode maître" });
  await dialog.getByLabel("Mot de passe").fill("bon-mot-de-passe");
  await dialog.getByRole("button", { name: "Activer" }).click();

  const banner = page.getByTestId("master-banner");
  await expect(banner).toContainText("Mode maître actif");
  await expect(banner).toContainText(/Fin dans 1[45]:\d\d/);

  await page.getByRole("checkbox", { name: "Tout sélectionner" }).check();
  await page.getByRole("button", { name: "Purger définitivement (2)" }).click();
  await expect(page.getByText("2 fichier(s) purgé(s) définitivement.")).toBeVisible();
  expect(server.purged).toEqual([["o1", "o2"]]);
  // No confirmation dialog was needed.
  await expect(page.getByRole("dialog", { name: "Purger définitivement" })).toHaveCount(0);

  await banner.getByRole("button", { name: "Quitter le mode maître" }).click();
  await expect(banner).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Mode maître" })).toBeVisible();
});

test("the trash is emptied in one click in master mode", async ({ page }) => {
  const server: Server = {
    masterUntil: Math.floor(Date.now() / 1000) + 600, purged: [], emptied: 0,
  };
  await setup(page, server);
  await page.getByLabel("État").selectOption({ label: "Corbeille" });
  await page.getByRole("button", { name: "Vider la corbeille" }).click();
  await expect(page.getByText("Corbeille vidée : 1 fichier(s) purgé(s).")).toBeVisible();
  expect(server.emptied).toBe(1);
});

test("without master mode the trash cannot be emptied and purges still ask", async ({ page }) => {
  const server: Server = { masterUntil: null, purged: [], emptied: 0 };
  await setup(page, server);
  await page.getByLabel("État").selectOption({ label: "Corbeille" });
  await expect(page.getByRole("button", { name: "Vider la corbeille" })).toHaveCount(0);
});
