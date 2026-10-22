import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * M03 upload flow — page-level wiring with mocked API and mocked presigned
 * endpoint (no real storage, no backend). It checks what only the browser can
 * show: real progress/phase display, the double-submit guard, backend-confirmed
 * success, server-error surfacing, expired-URL recovery and real cancellation.
 *
 * Retry/backoff timing is covered deterministically by transfer-engine.spec.ts.
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

interface Options {
  putDelayMs?: number;
  /** How many of the first PUTs answer 403 (expired signature) before success. */
  putExpiredTimes?: number;
  commitStatus?: number;
  commitDetail?: string;
}

interface Mocks {
  calls: string[];
  intentCount: () => number;
}

async function installMocks(page: Page, options: Options = {}): Promise<Mocks> {
  const calls: string[] = [];
  let intents = 0;
  let puts = 0;
  let objectId = "obj-1";

  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path === "/api/v1/login" && method === "POST") {
      await route.fulfill({ json: { csrf_token: CSRF } });
      return;
    }
    if (path === "/api/v1/me") {
      await route.fulfill({ json: ME });
      return;
    }
    if (path === "/api/v1/folders") {
      await route.fulfill({ json: { items: [] } });
      return;
    }
    if (path === "/api/v1/objects" && method === "GET") {
      await route.fulfill({ json: { items: [] } });
      return;
    }
    if (path === "/api/v1/objects/upload-intents" && method === "POST") {
      intents += 1;
      objectId = `obj-${intents}`;
      calls.push("intent");
      await route.fulfill({
        json: {
          id: objectId,
          status: "pending",
          method: "PUT",
          upload_url: `/fake-s3/put/${objectId}`,
          headers: { "Content-Type": "application/pdf" },
          content_type: "application/pdf",
          size_bytes: 11,
          expires_in: 900,
          expires_at: Math.floor(Date.now() / 1000) + 900,
          idempotent_replay: intents > 1,
        },
      });
      return;
    }
    if (/\/api\/v1\/objects\/[^/]+\/commit$/.test(path) && method === "POST") {
      calls.push("commit");
      if (options.commitStatus && options.commitStatus >= 400) {
        await route.fulfill({
          status: options.commitStatus,
          json: { detail: options.commitDetail ?? "error" },
        });
        return;
      }
      await route.fulfill({
        json: {
          id: objectId,
          status: "available",
          size_bytes: 11,
          checksum_sha256: "abc",
          checksum_algorithm: "sha256",
        },
      });
      return;
    }
    if (/\/api\/v1\/objects\/[^/]+\/abort$/.test(path) && method === "POST") {
      calls.push("abort");
      await route.fulfill({ json: { id: objectId, status: "aborted", aborted: true } });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });

  await page.route("**/fake-s3/**", async (route: Route) => {
    puts += 1;
    if (options.putDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.putDelayMs));
    }
    if (options.putExpiredTimes && puts <= options.putExpiredTimes) {
      calls.push("put-403");
      await route.fulfill({ status: 403, body: "expired" }).catch(() => undefined);
      return;
    }
    calls.push("put");
    await route.fulfill({ status: 200, body: "" }).catch(() => undefined);
  });

  return { calls, intentCount: () => intents };
}

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

async function chooseFile(page: Page, name = "rapport.pdf"): Promise<void> {
  await page.getByTestId('files-input').setInputFiles({
    name,
    mimeType: "application/pdf",
    buffer: Buffer.from("hello world"),
  });
}

test("upload shows name/size and confirms success only after commit", async ({ page }) => {
  const mocks = await installMocks(page);
  await login(page);
  await chooseFile(page, "rapport.pdf");
  await page.getByRole("button", { name: "Importer et valider" }).click();

  const status = page.getByRole("region", { name: /Import ·/ }).getByTestId("transfer-status");
  await expect(status).toContainText("rapport.pdf");
  await expect(status).toContainText("11 o");
  await expect(status).toContainText("Disponible");
  await expect(page.getByText("Import validé et vérifié par le backend.")).toBeVisible();

  // The order proves the UI never claims success before the backend commit.
  expect(mocks.calls).toEqual(["intent", "put", "commit"]);
});

test("blocks an accidental double submission", async ({ page }) => {
  const mocks = await installMocks(page, { putDelayMs: 2000 });
  await login(page);
  await chooseFile(page);

  const submit = page.getByRole("button", { name: "Importer et valider" });
  await submit.click();
  // While the upload is in flight the submit is disabled and only the cancel
  // control is offered, so a second submit cannot create a second intent.
  await expect(page.getByRole("button", { name: "Annuler" })).toBeVisible();
  await expect(submit).toBeDisabled();
  await expect(page.getByRole("region", { name: /Import ·/ }).getByTestId("transfer-status")).toContainText("Disponible");

  expect(mocks.intentCount()).toBe(1);
});

test("a server validation error is surfaced and never shown as success", async ({ page }) => {
  const mocks = await installMocks(page, {
    commitStatus: 422,
    commitDetail: "uploaded size does not match storage",
  });
  await login(page);
  await chooseFile(page);
  await page.getByRole("button", { name: "Importer et valider" }).click();

  // Scoped to the import panel: the page can show other alerts (e.g. storage usage).
  await expect(
    page.getByRole("region", { name: "Importer" }).getByRole("alert"),
  ).toContainText("incomplet ou différent de l'original");
  await expect(page.getByText("Import validé et vérifié par le backend.")).toHaveCount(0);
  expect(mocks.calls).toContain("commit");
});

test("recovers from an expired presigned URL with a fresh intent", async ({ page }) => {
  const mocks = await installMocks(page, { putExpiredTimes: 1 });
  await login(page);
  await chooseFile(page);
  await page.getByRole("button", { name: "Importer et valider" }).click();

  await expect(page.getByRole("region", { name: /Import ·/ }).getByTestId("transfer-status")).toContainText("Disponible");
  expect(mocks.calls.filter((call) => call === "intent")).toHaveLength(2);
  expect(mocks.calls.filter((call) => call === "put")).toHaveLength(1);
});

test("cancel aborts the backend intent and shows a cancelled state", async ({ page }) => {
  const mocks = await installMocks(page, { putDelayMs: 1500 });
  await login(page);
  await chooseFile(page);
  await page.getByRole("button", { name: "Importer et valider" }).click();
  await expect(page.getByRole("button", { name: "Annuler" })).toBeVisible();
  await page.getByRole("button", { name: "Annuler" }).click();
  // Stopping an import asks for confirmation (a stray click must not kill a
  // multi-hour import); "Annuler" in the dialog only closes it.
  await page.getByRole("button", { name: "Arrêter l'import" }).click();

  await expect(page.getByText("Import annulé.")).toBeVisible();
  await expect.poll(() => mocks.calls.includes("abort")).toBe(true);
  expect(mocks.calls).not.toContain("commit");
});

test("the cancel button asks before stopping, and keeping the import leaves it running", async ({ page }) => {
  const mocks = await installMocks(page, { putDelayMs: 1500 });
  await login(page);
  await chooseFile(page);
  await page.getByRole("button", { name: "Importer et valider" }).click();
  await page.getByRole("button", { name: "Annuler" }).first().click();
  await expect(page.getByRole("heading", { name: "Arrêter l'import ?" })).toBeVisible();
  expect(mocks.calls).not.toContain("abort");
});

test("a big batch lists only what needs attention; 'Tous' lists everything", async ({ page }) => {
  await installMocks(page, { putDelayMs: 300 });
  await login(page);
  // Several files start the import by themselves (auto-queue).
  await page.getByTestId("files-input").setInputFiles(
    Array.from({ length: 40 }, (_, i) => ({
      name: `lot-${i}.pdf`,
      mimeType: "application/pdf",
      buffer: Buffer.from("hello world"),
    })),
  );
  const tray = page.getByRole("region", { name: /Import ·/ }).getByTestId("transfer-status");
  await expect(tray.getByRole("group", { name: "Fichiers affichés" })).toBeVisible();
  // Finished files drop out of the default view: never all 40 rows at once.
  await expect(tray.locator("li.queue-item")).not.toHaveCount(40);
  await tray.getByRole("button", { name: "Tous" }).click();
  await expect(tray.locator("li.queue-item")).toHaveCount(40);
});

test("the tray explains what is happening to each file", async ({ page }) => {
  await installMocks(page, { putDelayMs: 1500 });
  await login(page);
  await chooseFile(page);
  await page.getByRole("button", { name: "Importer et valider" }).click();
  const tray = page.getByRole("region", { name: /Import ·/ }).getByTestId("transfer-status");
  await expect(tray.getByTestId("queue-breakdown")).toContainText("en envoi");
  await expect(tray.getByText("Envoi direct vers le stockage chiffré.")).toBeVisible();
  // The step shows how long it has lasted (m:ss).
  await expect(tray.locator(".elapsed").first()).toHaveText(/^\d+:\d{2}$/);
  await expect(tray.getByTestId("queue-breakdown")).toContainText("disponibles");
});

test("a file's details show its steps, object id and the server SHA-256", async ({ page }) => {
  await installMocks(page);
  await login(page);
  await chooseFile(page);
  await page.getByRole("button", { name: "Importer et valider" }).click();
  const tray = page.getByRole("region", { name: /Import ·/ }).getByTestId("transfer-status");
  await expect(tray.getByText("Disponible").first()).toBeVisible();
  await tray.getByRole("button", { name: "Détails de rapport.pdf" }).click();
  const detail = tray.getByTestId("file-detail");
  await expect(detail).toContainText("rapport.pdf");
  await expect(detail).toContainText("obj-1");
  await expect(detail).toContainText("abc");
  const steps = detail.getByRole("list", { name: "Étapes" });
  await expect(steps).toContainText("Autorisation demandée");
  await expect(steps).toContainText("Envoi des octets");
  await expect(steps).toContainText("Vérification d'intégrité");
  await expect(steps).toContainText("Disponible");
  await tray.getByRole("button", { name: "Détails de rapport.pdf" }).click();
  await expect(detail).toHaveCount(0);
});

test("the vault overview shows real figures and the empty state invites to import", async ({ page }) => {
  await installMocks(page);
  await page.route("**/api/v1/admin/usage**", (route) =>
    route.fulfill({
      json: {
        measured_at: 1,
        limits: { max_object_bytes: 5_368_709_120, max_pending_intents: 100, intent_ttl: 900, allow_empty_objects: false },
        capacity: { capacity_bytes: 1_000_000_000, high_watermark_pct: 90, accept_until_bytes: 900_000_000, stored_bytes: 800_000_000, reserved_bytes: 0, free_for_uploads_bytes: 100_000_000 },
        totals: { objects_by_status: { available: 3, pending: 1, verifying: 2 }, available_count: 3, stored_bytes: 800_000_000 },
        spaces: [],
      },
    }),
  );
  await login(page);
  const overview = page.getByTestId("vault-overview");
  await expect(overview).toContainText("Fichiers vérifiés");
  const tiles = overview.locator(".overview-tile");
  await expect(tiles.nth(1).locator(".overview-value")).toHaveText("3"); // verified
  await expect(tiles.nth(2).locator(".overview-value")).toHaveText("3"); // pending + verifying
  const meter = overview.getByRole("meter", { name: "Espace utilisé" });
  await expect(meter).toHaveAttribute("aria-valuenow", "80");
  await expect(meter).toHaveClass(/meter-warn/);
  // Empty catalogue: an invitation, with the import action.
  await expect(page.getByText("Aucun fichier dans ce dossier.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Importer des fichiers" })).toBeVisible();
});

test("a page that throws shows the branded error page, not the router default", async ({ page }) => {
  await installMocks(page);
  // A malformed usage answer makes the shell throw while rendering.
  await page.route("**/api/v1/admin/usage**", (route) => route.fulfill({ json: { totals: {} } }));
  // Not the shared login(): it waits for the files heading, which may already be gone.
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter" }).click();
  // The shell fetches usage after login: give the crash time under a loaded runner.
  await expect(page.getByRole("heading", { name: "Cette page n'a pas pu s'afficher" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByRole("button", { name: "Recharger la page" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Something went wrong!")).toHaveCount(0);
});
