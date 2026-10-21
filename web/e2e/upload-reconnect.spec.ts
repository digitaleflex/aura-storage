import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Automatic replay after a connectivity loss.
 *
 * A cut during the PUT used to leave the file in "Échec" until the user found
 * the "Réessayer les échecs" button, even though the failure was only the
 * link. The queue now keeps the window listeners and replays every transient
 * failure on the `online` event; fatal rejections still need a human.
 *
 * The API and the presigned endpoint are mocked, and the outage is driven by
 * the same `offline` / `online` events a browser fires, so the scenario is
 * deterministic (no real network, no real storage).
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

interface Link {
  /** While true, every presigned PUT fails like a dropped connection. */
  down: boolean;
  /** Released by the test: the held PUT stops waiting. */
  released: boolean;
}

async function installMocks(page: Page, link: Link): Promise<void> {
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
      return route.fulfill({
        json: { id, status: "available", size_bytes: 4, checksum_sha256: "abc" },
      });
    }
    if (/\/api\/v1\/objects\/[^/]+\/abort$/.test(path) && method === "POST") {
      return route.fulfill({ json: { id: "obj", status: "aborted", aborted: true } });
    }
    return route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });

  // The PUT is held open until the test cuts the link, so the outage hits a
  // transfer that is genuinely in flight instead of racing a fast response.
  await page.route("**/fake-s3/**", async (route: Route) => {
    for (let waited = 0; waited < 2000 && !link.released; waited += 1) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    if (link.down) return route.abort("internetdisconnected");
    return route.fulfill({ status: 200, body: "" });
  });
}

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

test("a file whose upload died with the link is replayed when the network returns", async ({
  page,
}) => {
  const link: Link = { down: false, released: false };
  await installMocks(page, link);
  await login(page);

  await page.getByTestId("files-input").setInputFiles({
    name: "alpha.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("aaaa"),
  });
  await expect(page.locator(".pending-item")).toHaveCount(1);
  await page.getByRole("button", { name: "Importer et valider" }).click();

  const status = page.getByTestId("transfer-status");
  await expect(status).toContainText("alpha.pdf");
  await expect(status).toContainText("Envoi");

  // The link drops: the browser announces it and the held PUT is lost.
  link.down = true;
  link.released = true;
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));

  await expect(page.getByText("Connexion perdue")).toBeVisible();
  // The in-flight file exhausts its own retries and is reported as failed...
  await expect(status.getByText("Échec", { exact: true })).toHaveCount(1, {
    timeout: 20_000,
  });

  // ...then the network comes back. No click on "Réessayer les échecs".
  link.down = false;
  await page.evaluate(() => window.dispatchEvent(new Event("online")));

  await expect(status.getByText("Disponible", { exact: true })).toHaveCount(1, {
    timeout: 20_000,
  });
  await expect(status.getByText("Échec", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText(/Connexion rétablie : 1 fichier relancé automatiquement/),
  ).toBeVisible();
  await expect(page.getByText("Connexion perdue")).toHaveCount(0);
});
