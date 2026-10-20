import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Multi-file upload queue (#63): select several files at once, transfer them
 * with bounded concurrency, isolate a failure and retry only the failed file.
 * The API and the presigned endpoint are mocked, so no real storage is needed.
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

async function installMocks(page: Page, state: { failBad: boolean }): Promise<void> {
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path === "/api/v1/login" && method === "POST") {
      return route.fulfill({ json: { csrf_token: CSRF } });
    }
    if (path === "/api/v1/me") return route.fulfill({ json: ME });
    if (path === "/api/v1/folders") return route.fulfill({ json: { items: [] } });
    if (path === "/api/v1/objects" && method === "GET") {
      return route.fulfill({ json: { items: [] } });
    }
    if (path === "/api/v1/objects/upload-intents" && method === "POST") {
      const body = request.postDataJSON() as { display_name: string; size_bytes: number };
      const id = `obj-${body.display_name}`;
      return route.fulfill({
        json: {
          id,
          status: "pending",
          method: "PUT",
          upload_url: `/fake-s3/put/${id}`,
          headers: { "Content-Type": "application/pdf" },
          content_type: "application/pdf",
          size_bytes: body.size_bytes,
          expires_in: 900,
          expires_at: Math.floor(Date.now() / 1000) + 900,
          idempotent_replay: false,
        },
      });
    }
    const commitMatch = path.match(/\/api\/v1\/objects\/([^/]+)\/commit$/);
    if (commitMatch && method === "POST") {
      const id = decodeURIComponent(commitMatch[1] ?? "");
      if (id.includes("bad") && state.failBad) {
        return route.fulfill({
          status: 422,
          json: { detail: "uploaded size does not match storage" },
        });
      }
      return route.fulfill({
        json: { id, status: "available", size_bytes: 10, checksum_sha256: "abc" },
      });
    }
    if (/\/api\/v1\/objects\/[^/]+\/abort$/.test(path) && method === "POST") {
      return route.fulfill({ json: { id: "obj", status: "aborted", aborted: true } });
    }
    return route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });

  await page.route("**/fake-s3/**", (route) => route.fulfill({ status: 200, body: "" }));
}

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

test("queues several files, isolates one failure and retries only it", async ({ page }) => {
  const state = { failBad: true };
  await installMocks(page, state);
  await login(page);

  await page.getByTestId('files-input').setInputFiles([
    { name: "alpha.pdf", mimeType: "application/pdf", buffer: Buffer.from("aaaa") },
    { name: "bad.pdf", mimeType: "application/pdf", buffer: Buffer.from("bbbb") },
    { name: "gamma.pdf", mimeType: "application/pdf", buffer: Buffer.from("cccc") },
  ]);

  // All three are staged before submission.
  await expect(page.locator(".pending-item")).toHaveCount(3);

  await page.getByRole("button", { name: "Importer et valider" }).click();

  const status = page.getByTestId("transfer-status");
  await expect(status).toContainText("alpha.pdf");
  await expect(status).toContainText("bad.pdf");
  await expect(status).toContainText("gamma.pdf");

  // Two succeed, one fails, and the failure is surfaced with its detail.
  await expect(status.getByText("Disponible", { exact: true })).toHaveCount(2);
  await expect(status.getByText("Échec", { exact: true })).toHaveCount(1);
  // Scoped to the import panel: the page can show other alerts (e.g. storage usage).
  await expect(
    page.getByRole("region", { name: "Importer" }).getByRole("alert"),
  ).toContainText("incomplet ou différent de l'original");

  // Retry only the failed file; the two successes are not re-uploaded.
  state.failBad = false;
  await page.getByRole("button", { name: "Réessayer les échecs" }).click();
  await expect(status.getByText("Disponible", { exact: true })).toHaveCount(3);
  await expect(status.getByText("Échec", { exact: true })).toHaveCount(0);
});
