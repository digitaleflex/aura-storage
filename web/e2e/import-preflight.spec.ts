import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

const CSRF = "csrf-test";
const ME = {
  id: "u1",
  kind: "user",
  role: "admin",
  space_id: "s1",
  application_id: "a1",
  scopes: ["objects:read", "objects:write", "objects:delete", "objects:purge"],
};

async function installMocks(page: Page, existing: Array<Record<string, unknown>> = []) {
  let intents = 0;
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/api/v1/login" && method === "POST") {
      return route.fulfill({ json: { csrf_token: CSRF } });
    }
    if (path === "/api/v1/me") return route.fulfill({ json: ME });
    if (path === "/api/v1/folders" && method === "GET") {
      return route.fulfill({ json: { items: [] } });
    }
    if (path === "/api/v1/objects" && method === "GET") {
      return route.fulfill({ json: { items: existing } });
    }
    if (path === "/api/v1/objects/duplicate-scan" && method === "POST") {
      return route.fulfill({
        json: { byParent: existing.length ? { "": existing } : {}, unresolved: [] },
      });
    }
    if (path === "/api/v1/objects/upload-intents" && method === "POST") {
      intents += 1;
      const body = request.postDataJSON();
      return route.fulfill({
        json: {
          id: `obj-${intents}`,
          status: "pending",
          method: "PUT",
          upload_url: `/fake-s3/${intents}`,
          headers: {},
          content_type: body.content_type,
          size_bytes: body.size_bytes,
          expires_in: 900,
          expires_at: Math.floor(Date.now() / 1000) + 900,
        },
      });
    }
    if (/\/api\/v1\/objects\/[^/]+\/commit$/.test(path) && method === "POST") {
      return route.fulfill({ json: { id: "obj", status: "available", size_bytes: 1, checksum_sha256: "abc" } });
    }
    return route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });
  await page.route("**/fake-s3/**", (route) => route.fulfill({ status: 200, body: "" }));
  return { intentCount: () => intents };
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

test("stages several folders and files, verifies progressively and never auto-imports", async ({ page }) => {
  const mocks = await installMocks(page);
  await login(page);

  const first = mkdtempSync(join(tmpdir(), "aura-import-a-"));
  const second = mkdtempSync(join(tmpdir(), "aura-import-b-"));
  mkdirSync(join(first, "Contrats"), { recursive: true });
  writeFileSync(join(first, "a.pdf"), "a");
  writeFileSync(join(first, "Contrats", "b.pdf"), "b");
  writeFileSync(join(second, "c.pdf"), "c");

  await page.getByTestId("folder-input").setInputFiles(first);
  await page.getByTestId("folder-input").setInputFiles(second);
  await page.getByTestId("files-input").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("notes"),
  });

  const preflight = page.getByTestId("import-preflight");
  await expect(preflight).toBeVisible();
  await expect(preflight).toContainText(basename(first));
  await expect(preflight).toContainText(basename(second));
  await expect(preflight).toContainText("Fichiers individuels");
  await expect(page.getByRole("button", { name: "Ajouter un autre dossier…" })).toBeVisible();
  await expect(preflight.getByTestId("preflight-item")).toHaveCount(4);
  await expect(preflight.locator('[data-status="ready"]')).toHaveCount(4);

  // A selection is staging only: no intent is created before explicit submit.
  await page.waitForTimeout(800);
  expect(mocks.intentCount()).toBe(0);

  await page.getByRole("button", { name: `Retirer le dossier ${basename(first)}` }).click();
  await expect(preflight).not.toContainText(basename(first));
  await expect(preflight).toContainText(basename(second));
});

test("shows an existing duplicate during selection and offers to skip it", async ({ page }) => {
  const mocks = await installMocks(page, [
    {
      id: "existing",
      display_name: "rapport.pdf",
      content_type: "application/pdf",
      size_bytes: 11,
      checksum_sha256: "",
      status: "available",
      folder_id: null,
      created_at: 1,
      updated_at: 1,
    },
  ]);
  await login(page);
  await page.getByTestId("files-input").setInputFiles({
    name: "rapport.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("hello world"),
  });

  const preflight = page.getByTestId("import-preflight");
  const item = preflight.getByTestId("preflight-item");
  await expect(item).toHaveAttribute("data-status", "duplicate");
  await expect(item).toContainText("Doublon · nom + taille identiques");

  await page.getByRole("button", { name: "Importer et valider" }).click();
  await expect(page.getByRole("dialog", { name: "Doublons détectés" })).toBeVisible();
  await page.getByRole("button", { name: "Ignorer les doublons" }).click();
  await expect(page.getByText("Tous les fichiers sélectionnés sont des doublons — import annulé.")).toBeVisible();
  expect(mocks.intentCount()).toBe(0);
});

test("active import preflight has no critical axe violations", async ({ page }) => {
  await installMocks(page);
  await login(page);
  await page.getByTestId("files-input").setInputFiles({
    name: "rapport.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("hello world"),
  });
  await expect(page.getByTestId("import-preflight")).toBeVisible();
  const results = await new AxeBuilder({ page }).include("#intake").analyze();
  expect(results.violations).toEqual([]);
});
