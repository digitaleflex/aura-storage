import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Layout of a multipart transfer row. A large file is sent in many parts (a
 * 600 Mo file was 122 parts): the row must never widen the table past its panel,
 * hide the status/actions columns behind a horizontal scroll, or show a part
 * counter that contradicts the progress bar. API and part PUTs are mocked.
 */

const PART = 8;
const PARTS = 150;
const SIZE = PART * PARTS;

const ME = {
  id: "u1", kind: "user", name: "admin", role: "admin", space_id: "s1",
  application_id: "a1", scopes: ["objects:read", "objects:write"], csrf_token: "csrf-test",
};

async function mock(page: Page) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/api/v1/login") return route.fulfill({ json: { csrf_token: "csrf-test" } });
    if (path === "/api/v1/me") return route.fulfill({ json: ME });
    if (path === "/api/v1/folders") return route.fulfill({ json: { items: [] } });
    if (path === "/api/v1/objects" && method === "GET") return route.fulfill({ json: { items: [] } });
    if (path === "/api/v1/objects/upload-intents") {
      return route.fulfill({
        json: {
          id: "obj-big", status: "pending", method: "PUT", upload_mode: "multipart",
          upload_url: null, headers: {}, content_type: "application/octet-stream",
          size_bytes: SIZE, multipart: { part_size_bytes: PART, part_count: PARTS },
          expires_in: 600000, expires_at: null, idempotent_replay: false,
        },
      });
    }
    if (path === "/api/v1/objects/obj-big/multipart") {
      return route.fulfill({
        json: { id: "obj-big", size_bytes: SIZE, part_size_bytes: PART, part_count: PARTS, uploaded_parts: [] },
      });
    }
    if (path === "/api/v1/objects/obj-big/multipart/parts") {
      const { part_numbers } = request.postDataJSON() as { part_numbers: number[] };
      return route.fulfill({
        json: {
          id: "obj-big", expires_in: 900,
          parts: part_numbers.map((n) => ({ part_number: n, size_bytes: 0, url: `/fake-s3/part?partNumber=${n}` })),
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: "unmocked" } });
  });
  // Parts stay in flight: the row keeps its "uploading" layout.
  await page.route("**/fake-s3/**", async (route: Route) => {
    await new Promise((resolve) => setTimeout(resolve, 20_000));
    await route.fulfill({ status: 200, body: "" }).catch(() => undefined);
  });
}

async function openTransfers(page: Page) {
  await mock(page);
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();

  await page.getByTestId("files-input").setInputFiles([
    { name: "gros-livre.mp3", mimeType: "audio/mpeg", buffer: Buffer.alloc(SIZE, 1) },
  ]);
  await page.getByRole("button", { name: "Importer et valider" }).click();
  await page.getByRole("link", { name: "Transferts", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Transferts" })).toBeVisible();
  const row = page.getByTestId("transfer-row").first();
  await expect(row).toBeVisible();
  return row;
}

test("a many-part transfer neither widens the page nor hides its status", async ({ page }) => {
  await openTransfers(page);

  // No horizontal scroll on the page, and the status column stays on screen.
  const geometry = await page.evaluate(() => {
    const badge = document.querySelector(".transfers-row .transfer-badge");
    return {
      pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      badgeRight: badge ? badge.getBoundingClientRect().right : null,
      viewport: window.innerWidth,
    };
  });
  expect(geometry.pageOverflow).toBeLessThanOrEqual(0);
  expect(geometry.badgeRight).not.toBeNull();
  expect(geometry.badgeRight as number).toBeLessThanOrEqual(geometry.viewport);
});

test("the part counter never claims every part is missing while bytes are sent", async ({ page }) => {
  const row = await openTransfers(page);
  await expect(row.getByText(`${PARTS} parties`)).toBeVisible();
  await expect(row.getByText(/manquante/)).toHaveCount(0);
});
