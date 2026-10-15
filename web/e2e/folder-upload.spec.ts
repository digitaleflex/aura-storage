import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

/**
 * Directory upload (#64): selecting a folder recreates its tree via the folder
 * API and uploads each file into the matching folder_id. The API and the
 * presigned endpoint are mocked, so no real storage is used.
 */

const CSRF = "csrf-test";
const ME = {
  id: "u1",
  kind: "user",
  role: "admin",
  space_id: "s1",
  application_id: "a1",
  scopes: ["objects:read", "objects:write", "objects:delete", "objects:purge"],
};

interface CreatedFolder {
  name: string;
  parent_id: string | null;
}
interface Intent {
  name: string;
  folder_id: string | null;
}

async function installMocks(
  page: Page,
  state: { folders: CreatedFolder[]; intents: Intent[] },
): Promise<void> {
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
    if (path === "/api/v1/folders" && method === "POST") {
      const body = request.postDataJSON() as CreatedFolder;
      state.folders.push(body);
      return route.fulfill({
        json: {
          id: `folder-${body.name}`,
          name: body.name,
          parent_id: body.parent_id ?? null,
          created_at: 1,
        },
      });
    }
    if (path === "/api/v1/objects" && method === "GET") {
      return route.fulfill({ json: { items: [] } });
    }
    if (path === "/api/v1/objects/upload-intents" && method === "POST") {
      const body = request.postDataJSON() as {
        display_name: string;
        size_bytes: number;
        folder_id?: string | null;
      };
      state.intents.push({ name: body.display_name, folder_id: body.folder_id ?? null });
      return route.fulfill({
        json: {
          id: `obj-${body.display_name}`,
          status: "pending",
          method: "PUT",
          upload_url: `/fake-s3/put/${body.display_name}`,
          headers: { "Content-Type": "application/pdf" },
          content_type: "application/pdf",
          size_bytes: body.size_bytes,
          expires_in: 900,
          expires_at: Math.floor(Date.now() / 1000) + 900,
          idempotent_replay: false,
        },
      });
    }
    const commit = path.match(/\/api\/v1\/objects\/([^/]+)\/commit$/);
    if (commit && method === "POST") {
      return route.fulfill({
        json: {
          id: decodeURIComponent(commit[1] ?? ""),
          status: "available",
          size_bytes: 1,
          checksum_sha256: "abc",
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });
  await page.route("**/fake-s3/**", (route) => route.fulfill({ status: 200, body: "" }));
}

test("imports a folder tree and uploads files into the recreated folders", async ({
  page,
}) => {
  const root = mkdtempSync(join(tmpdir(), "aura-dir-"));
  const base = basename(root);
  mkdirSync(join(root, "Contrats", "2026"), { recursive: true });
  writeFileSync(join(root, "notes.txt"), "n");
  writeFileSync(join(root, "Contrats", "a.pdf"), "a");
  writeFileSync(join(root, "Contrats", "2026", "b.pdf"), "b");

  const state: { folders: CreatedFolder[]; intents: Intent[] } = {
    folders: [],
    intents: [],
  };
  await installMocks(page, state);

  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Fichiers" })).toBeVisible();

  await page.getByTestId("folder-input").setInputFiles(root);

  // Nothing is created before the user confirms.
  expect(state.folders).toHaveLength(0);

  // Wait for the tree to be recreated: parents before children.
  await expect.poll(() => state.folders.length).toBe(3);
  const byName = new Map(state.folders.map((f) => [f.name, f.parent_id]));
  expect(byName.get(base)).toBeNull();
  expect(byName.get("Contrats")).toBe(`folder-${base}`);
  expect(byName.get("2026")).toBe("folder-Contrats");

  // Each file targets the folder it lived in.
  await expect.poll(() => state.intents.length).toBe(3);
  const target = new Map(state.intents.map((i) => [i.name, i.folder_id]));
  expect(target.get("notes.txt")).toBe(`folder-${base}`);
  expect(target.get("a.pdf")).toBe("folder-Contrats");
  expect(target.get("b.pdf")).toBe("folder-2026");

  // All three end up available.
  await expect(page.getByTestId("transfer-status").getByText("Disponible", { exact: true })).toHaveCount(3);
});
