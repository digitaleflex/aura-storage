import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/**
 * #72 in the page: a large file goes up in parts; after a failure and a page
 * reload, the resumed import reuses the same server session (same
 * Idempotency-Key) and sends only the parts the storage does not hold. The API
 * and the part PUTs are mocked; nothing reaches a real storage.
 */

const PART = 8;
const SIZE = 37; // 5 parts

const ME = {
  id: "u1", kind: "user", name: "admin", role: "admin", space_id: "s1",
  application_id: "a1", scopes: ["objects:read", "objects:write"], csrf_token: "csrf-test",
};

interface Server {
  held: Set<number>;
  rejectPart: number | null;
  keys: string[];
  puts: number[];
}

async function mock(page: Page, server: Server) {
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path === "/api/v1/login") return route.fulfill({ json: { csrf_token: "csrf-test" } });
    if (path === "/api/v1/me") return route.fulfill({ json: ME });
    if (path === "/api/v1/folders") return route.fulfill({ json: { items: [] } });
    if (path === "/api/v1/objects" && method === "GET") return route.fulfill({ json: { items: [] } });
    if (path === "/api/v1/objects/upload-intents") {
      server.keys.push(request.headers()["idempotency-key"] ?? "");
      return route.fulfill({
        json: {
          id: "obj-big", status: "pending", method: "PUT", upload_mode: "multipart",
          upload_url: null, headers: {}, content_type: "application/octet-stream",
          size_bytes: SIZE, multipart: { part_size_bytes: PART, part_count: 5 },
          expires_in: 600000, expires_at: null, idempotent_replay: server.keys.length > 1,
        },
      });
    }
    if (path === "/api/v1/objects/obj-big/multipart") {
      return route.fulfill({
        json: {
          id: "obj-big", size_bytes: SIZE, part_size_bytes: PART, part_count: 5,
          uploaded_parts: [...server.held].sort(),
        },
      });
    }
    if (path === "/api/v1/objects/obj-big/multipart/parts") {
      const { part_numbers } = request.postDataJSON() as { part_numbers: number[] };
      return route.fulfill({
        json: {
          id: "obj-big", expires_in: 900,
          parts: part_numbers.map((n) => ({
            part_number: n, size_bytes: 0, url: `/fake-s3/part?partNumber=${n}`,
          })),
        },
      });
    }
    if (path === "/api/v1/objects/obj-big/commit") {
      return route.fulfill({
        json: { id: "obj-big", status: "available", size_bytes: SIZE, checksum_sha256: "abc" },
      });
    }
    return route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });
  await page.route("**/fake-s3/**", (route) => {
    const n = Number(new URL(route.request().url()).searchParams.get("partNumber"));
    server.puts.push(n);
    if (n === server.rejectPart) return route.fulfill({ status: 400, body: "" });
    server.held.add(n);
    return route.fulfill({ status: 200, body: "" });
  });
}

test("a large file resumes after a reload with only its missing parts", async ({ page }) => {
  const dir = test.info().outputPath("files");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, "video.bin");
  writeFileSync(path, Buffer.alloc(SIZE, 7));

  const server: Server = { held: new Set(), rejectPart: 4, keys: [], puts: [] };
  await mock(page, server);
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("x");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();

  await page.getByTestId("files-input").setInputFiles([path]);
  await page.getByRole("button", { name: "Importer et valider" }).click();
  const status = page.getByTestId("transfer-status");
  await expect(status.getByText("Échec", { exact: true })).toHaveCount(1);
  expect(server.held.has(4)).toBe(false);

  // Reload, then resume: same session key, only the missing part(s) are sent.
  server.rejectPart = null;
  server.puts = [];
  await page.reload();
  await page.getByTestId("resume-files-input").setInputFiles([path]);
  await expect(status.getByText("Disponible", { exact: true })).toHaveCount(1);
  expect(server.keys).toHaveLength(2);
  expect(server.keys[1]).toBe(server.keys[0]);
  expect(server.puts).not.toContain(1);
  expect(server.puts).toContain(4);
  expect(server.held.size).toBe(5);
});
