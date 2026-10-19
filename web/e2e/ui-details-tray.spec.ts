import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * UI v2 step 3: the details panel, the floating upload tray and the sortable
 * column headers. The whole API and the presigned PUT are mocked, so nothing is
 * created in the shared catalogue and S3 is never contacted. Vite serves the SPA
 * on 127.0.0.1:5173.
 */

const FILE = {
  id: "obj-1",
  display_name: "contrat-cadre.pdf",
  content_type: "application/pdf",
  size_bytes: 2_483_212,
  status: "available",
  folder_id: null,
  checksum_sha256: "3ec4bff4fd455b9c930ac8f5b413fa379162de39d7929c65d63a488be0c4d8b6",
  created_at: 1_700_000_000,
  updated_at: 1_700_000_500,
};

async function mockApi(page: Page, putDelayMs = 0): Promise<string[]> {
  const objectQueries: string[] = [];
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path === "/api/v1/login") {
      await route.fulfill({ json: { csrf_token: "csrf-test" } });
    } else if (path === "/api/v1/me") {
      await route.fulfill({
        json: {
          id: "u1", kind: "user", name: "admin", role: "admin", space_id: "s1",
          application_id: "a1", scopes: ["objects:read", "objects:purge"],
          csrf_token: "csrf-test",
        },
      });
    } else if (path === "/api/v1/folders") {
      await route.fulfill({ json: { items: [] } });
    } else if (path === "/api/v1/objects" && method === "GET") {
      objectQueries.push(url.search);
      await route.fulfill({ json: { items: [FILE] } });
    } else if (path === "/api/v1/objects/upload-intents") {
      await route.fulfill({
        json: {
          id: "obj-2", status: "pending", method: "PUT",
          upload_url: "/fake-s3/put/obj-2", headers: { "Content-Type": "application/pdf" },
          content_type: "application/pdf", size_bytes: 11, expires_in: 900,
          expires_at: Math.floor(Date.now() / 1000) + 900, idempotent_replay: false,
        },
      });
    } else if (/\/commit$/.test(path)) {
      await route.fulfill({
        json: {
          id: "obj-2", status: "available", size_bytes: 11,
          checksum_sha256: "abc", checksum_algorithm: "sha256",
        },
      });
    } else {
      await route.fulfill({ status: 404, json: { detail: "not mocked" } });
    }
  });
  await page.route("**/fake-s3/**", async (route: Route) => {
    if (putDelayMs) await new Promise((resolve) => setTimeout(resolve, putDelayMs));
    await route.fulfill({ status: 200, body: "" }).catch(() => undefined);
  });
  return objectQueries;
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

test("the details panel leads with status and keeps destructive actions apart", async ({
  page,
}) => {
  await mockApi(page);
  await login(page);
  await page.getByRole("button", { name: `Détails de ${FILE.display_name}` }).click();

  const panel = page.getByRole("dialog", { name: FILE.display_name });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Disponible et vérifié")).toBeVisible();
  // The name is the title only: it is not repeated as a field.
  await expect(panel.getByRole("heading", { level: 2, name: FILE.display_name })).toBeVisible();
  await expect(panel.locator(".detail-list")).not.toContainText(FILE.display_name);
  await expect(panel.getByText(FILE.checksum_sha256)).toBeVisible();

  const danger = panel.locator(".drawer-danger");
  await expect(danger.getByRole("heading", { name: "Zone sensible" })).toBeVisible();
  await expect(danger.getByRole("button", { name: "Supprimer" })).toBeVisible();
  await expect(danger.getByRole("button", { name: "Purger définitivement" })).toBeVisible();
  // The primary actions stay outside the sensitive zone.
  await expect(panel.getByRole("button", { name: "Télécharger" })).toBeVisible();
  await expect(danger.getByRole("button", { name: "Télécharger" })).toHaveCount(0);
});

test("column headers sort server-side and show the direction", async ({ page }) => {
  const queries = await mockApi(page);
  await login(page);

  const added = page.getByRole("button", { name: /^Ajouté/ });
  await expect(added).toContainText("tri décroissant");

  await page.getByRole("button", { name: /^Taille/ }).click();
  await expect
    .poll(() => queries.some((q) => q.includes("sort=size_bytes") && q.includes("order=desc")))
    .toBe(true);
  await page.getByRole("button", { name: /^Taille/ }).click();
  await expect
    .poll(() => queries.some((q) => q.includes("sort=size_bytes") && q.includes("order=asc")))
    .toBe(true);
  await expect(page.getByRole("button", { name: /^Taille/ })).toContainText("tri croissant");
});

test("uploads show in a floating tray that stays in view and can be folded", async ({
  page,
}) => {
  await mockApi(page, 1500);
  await login(page);

  await page.getByRole("button", { name: "Importer", exact: true }).click();
  await page.getByTestId("files-input").setInputFiles({
    name: "plan-site.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("hello world"),
  });
  await page.getByRole("button", { name: "Importer et valider" }).click();

  const tray = page.getByRole("region", { name: /^Import ·/ });
  await expect(tray).toBeVisible();
  await expect(tray).toBeInViewport();
  await expect(tray.getByTestId("transfer-status")).toContainText("plan-site.pdf");

  // Folding hides the list but keeps the summary; unfolding restores it.
  await tray.getByRole("button", { name: "Réduire" }).click();
  await expect(tray.getByTestId("transfer-status")).toBeHidden();
  await tray.getByRole("button", { name: "Agrandir" }).click();
  await expect(tray.getByTestId("transfer-status")).toBeVisible();

  // Once finished the tray can be cleared.
  await expect(tray).toContainText("1 sur 1 terminé", { timeout: 10_000 });
  await tray.getByRole("button", { name: "Effacer" }).click();
  await expect(tray).toHaveCount(0);
});

test("on a phone the notification stack never blocks the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await login(page);

  // The (empty) toast stack used to stretch over the whole screen on phones
  // and swallow every tap on the list.
  await page.getByRole("button", { name: `Détails de ${FILE.display_name}` }).click();
  await expect(page.getByRole("dialog", { name: FILE.display_name })).toBeVisible();
});
