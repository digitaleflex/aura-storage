import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Vault UI behaviours (S16) — page-level checks with a fully mocked API and a
 * mocked presigned endpoint (no real storage, no backend contact). These cover
 * behaviours that only the browser can show, so they stay offline:
 *
 *  1. a drop landing while a transfer is in flight is buffered as a real
 *     backlog (never swallowed silently) — `pendingFiles` in ObjectsPage;
 *  2. a refused (409) folder deletion is actionable: friendly FR + "Réessayer"
 *     that re-issues the DELETE until it succeeds — `folderDeleteError`;
 *  3. storage usage is gated on `admin:read` (operator/admin only): a plain
 *     `user` never calls `GET /api/v1/admin/usage` and never sees usage;
 *  4. the "SHA-256 vérifié" chip appears only once a queue item reaches the
 *     `available` phase, never while it is still moving;
 *  5. the accepted import categories are informative text, not controls.
 *
 * The mock mirrors e2e/upload-flow.spec.ts: `page.route` answers every /api/v1
 * call and the presigned PUT, so no uvicorn/Vite backend data is needed beyond
 * the dev server that serves the SPA build.
 */

const CSRF = "csrf-test";

interface FolderItem {
  id: string;
  name: string;
  parent_id: string | null;
  created_at: number;
}

interface Me {
  id: string;
  kind: string;
  role: string;
  space_id: string;
  application_id: string;
  scopes: string[];
}

function me(role: string): Me {
  return {
    id: "u1",
    kind: "user",
    role,
    space_id: "s1",
    application_id: "a1",
    scopes: [
      "objects:read",
      "objects:write",
      "objects:delete",
      "objects:purge",
    ],
  };
}

const USAGE = {
  measured_at: 1_700_000_000,
  limits: {
    max_object_bytes: 0,
    max_pending_intents: 0,
    intent_ttl: 0,
    allow_empty_objects: false,
  },
  totals: {
    objects_by_status: { available: 1 },
    available_count: 1,
    // 2048 bytes -> "2.0 Ko" via the page's formatBytes.
    stored_bytes: 2048,
  },
  spaces: [],
};

interface Options {
  role?: string;
  folders?: FolderItem[];
  /** Successive DELETE /folders/{id} statuses; the last one repeats. */
  folderDeleteStatuses?: number[];
  putDelayMs?: number;
  /** Whether GET /admin/usage is answered 200 (true) or left to 404. */
  usage?: boolean;
}

interface Mocks {
  calls: string[];
  usageRequests: () => number;
}

async function installMocks(page: Page, options: Options = {}): Promise<Mocks> {
  const calls: string[] = [];
  let usageRequests = 0;
  let objectId = "obj-1";
  let deletes = 0;
  const deleteStatuses = options.folderDeleteStatuses ?? [200];

  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path === "/api/v1/login" && method === "POST") {
      await route.fulfill({ json: { csrf_token: CSRF } });
      return;
    }
    if (path === "/api/v1/me") {
      await route.fulfill({ json: me(options.role ?? "admin") });
      return;
    }
    if (path === "/api/v1/folders" && method === "GET") {
      // After a successful delete the (mock) tree no longer holds the folder.
      const items = deletes > 0 ? [] : (options.folders ?? []);
      await route.fulfill({ json: { items } });
      return;
    }
    if (/\/api\/v1\/folders\/[^/]+$/.test(path) && method === "DELETE") {
      const status =
        deleteStatuses[Math.min(deletes, deleteStatuses.length - 1)] ?? 200;
      deletes += 1;
      calls.push(`delete-folder:${status}`);
      if (status >= 400) {
        await route.fulfill({
          status,
          json: { detail: "folder is not empty" },
        });
        return;
      }
      await route.fulfill({ json: { id: "f-1", status: "deleted" } });
      return;
    }
    if (path === "/api/v1/objects" && method === "GET") {
      await route.fulfill({ json: { items: [] } });
      return;
    }
    if (path === "/api/v1/objects/upload-intents" && method === "POST") {
      objectId = `obj-${calls.filter((c) => c === "intent").length + 1}`;
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
          idempotent_replay: false,
        },
      });
      return;
    }
    if (/\/api\/v1\/objects\/[^/]+\/commit$/.test(path) && method === "POST") {
      calls.push("commit");
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
    if (path === "/api/v1/admin/usage" && method === "GET") {
      usageRequests += 1;
      calls.push("admin-usage");
      if (options.usage === false) {
        await route.fulfill({ status: 404, json: { detail: "unmocked usage" } });
        return;
      }
      await route.fulfill({ json: USAGE });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });

  await page.route("**/fake-s3/**", async (route: Route) => {
    if (options.putDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.putDelayMs));
    }
    await route.fulfill({ status: 200, body: "" }).catch(() => undefined);
  });

  return { calls, usageRequests: () => usageRequests };
}

async function login(page: Page, role = "admin"): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill(role);
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fichiers" })).toBeVisible();
}

async function chooseFile(page: Page, name = "rapport.pdf"): Promise<void> {
  await page.getByTestId("files-input").setInputFiles({
    name,
    mimeType: "application/pdf",
    buffer: Buffer.from("hello world"),
  });
}

/** Dispatch a real `drop` carrying loose files at the intake drop zone. */
async function dropLooseFiles(
  page: Page,
  files: { name: string; type: string; content: string }[],
): Promise<void> {
  const dataTransfer = await page.evaluateHandle((items) => {
    const dt = new DataTransfer();
    for (const item of items) {
      dt.items.add(new File([item.content], item.name, { type: item.type }));
    }
    return dt;
  }, files);
  await page.locator("section.intake").dispatchEvent("drop", { dataTransfer });
}

// -- 1. backlog drop during an active transfer -----------------------------

test("a drop during a transfer is buffered as a backlog, never swallowed", async ({
  page,
}) => {
  await installMocks(page, { putDelayMs: 2500 });
  await login(page);

  // Start a transfer and let it reach the in-flight state.
  await chooseFile(page, "en-cours.pdf");
  await page.getByRole("button", { name: "Importer et valider" }).click();
  await expect(page.getByRole("button", { name: "Annuler" })).toBeVisible();

  // Drop a loose file while the queue is busy.
  await dropLooseFiles(page, [
    { name: "backlog.txt", type: "text/plain", content: "buffered" },
  ]);

  // The drop is acknowledged and the file is held for the next run.
  await expect(page.getByText(/ajouté\(s\) à la file d'attente/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retirer backlog.txt" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "En attente du prochain import — le transfert en cours se termine d'abord.",
    ),
  ).toBeVisible();

  // The drop never started a second intent: only the first file was submitted.
  await expect(page.getByTestId("transfer-status")).toContainText("en-cours.pdf");
});

// -- 2. actionable 409 folder-delete retry ---------------------------------

test("a refused (409) folder deletion offers a working Réessayer", async ({ page }) => {
  const mocks = await installMocks(page, {
    folders: [{ id: "f-1", name: "Photos", parent_id: null, created_at: 0 }],
    folderDeleteStatuses: [409, 200],
  });
  await login(page);

  const open = page.getByRole("button", { name: "Photos", exact: true });
  await expect(open).toBeVisible();

  // Request deletion: the server refuses a non-empty folder.
  await page.getByRole("button", { name: "Actions pour le dossier Photos" }).click();
  await page.getByRole("menuitem", { name: "Supprimer" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Supprimer" })
    .click();

  const deleteCalls = () =>
    mocks.calls.filter((call) => call.startsWith("delete-folder:"));
  const refusal = page.getByRole("alert").filter({ hasText: "n'est pas vide" });
  await expect(refusal).toBeVisible();
  await expect(refusal).toContainText("Photos");
  await expect.poll(deleteCalls).toEqual(["delete-folder:409"]);
  // The folder is not removed on a refusal.
  await expect(open).toBeVisible();

  // Retry: the second DELETE succeeds and the actionable alert clears.
  await refusal.getByRole("button", { name: "Réessayer" }).click();
  await expect(open).toHaveCount(0);
  await expect(
    page.getByRole("alert").filter({ hasText: "n'est pas vide" }),
  ).toHaveCount(0);
  expect(deleteCalls()).toEqual(["delete-folder:409", "delete-folder:200"]);
});

// -- 3. storage usage gating (admin:read) -----------------------------------

test("storage usage is never fetched nor shown for a plain user", async ({ page }) => {
  const mocks = await installMocks(page, { role: "user", usage: true });
  await login(page, "user");

  // No admin:read -> the admin usage query must stay disabled.
  await expect(page.getByRole("heading", { name: "Fichiers" })).toBeVisible();
  expect(mocks.usageRequests()).toBe(0);
  await expect(page.getByText("Espace utilisé")).toHaveCount(0);
  await expect(page.getByText(/Usage réel \(admin\)/)).toHaveCount(0);
});

test("storage usage is fetched and shown for an operator (admin:read)", async ({
  page,
}) => {
  const mocks = await installMocks(page, { role: "operator", usage: true });
  await login(page, "operator");

  await expect.poll(() => mocks.usageRequests()).toBe(1);
  await expect(page.getByText("Espace utilisé")).toBeVisible();
  // 2048 bytes renders as "2.0 Ko" (real figure, not fabricated capacity).
  await expect(page.getByText("2.0 Ko")).toBeVisible();
  await expect(page.getByText(/Usage réel \(admin\)/)).toBeVisible();
});

// -- 4. conditional SHA-256 chip --------------------------------------------

test("the SHA-256 chip only appears once a file is available", async ({ page }) => {
  await installMocks(page, { putDelayMs: 3000 });
  await login(page);
  await chooseFile(page, "rapport.pdf");
  await page.getByRole("button", { name: "Importer et valider" }).click();

  // While the file is still moving the checksum is not (yet) claimed.
  await expect(page.getByTestId("transfer-status")).toContainText("Envoi…");
  await expect(page.getByText("SHA-256 vérifié", { exact: true })).toHaveCount(0);

  // Once committed and available, the verified chip is shown.
  await expect(page.getByTestId("transfer-status")).toContainText("Disponible");
  await expect(page.getByText("SHA-256 vérifié", { exact: true })).toBeVisible();
});

// -- 5. informational (non-interactive) category badges ---------------------

test("accepted import categories are informative, not interactive", async ({ page }) => {
  await installMocks(page);
  await login(page);

  const categories = page.getByRole("list", {
    name: "Catégories de fichiers acceptées",
  });
  await expect(categories).toBeVisible();

  for (const label of [
    "Documents",
    "Images",
    "Vidéos",
    "Audio",
    "Archives",
    "Autres",
  ]) {
    await expect(categories.getByText(label, { exact: true })).toBeVisible();
  }

  // They carry no control: no buttons, no links inside the badge list.
  await expect(categories.getByRole("button")).toHaveCount(0);
  await expect(categories.getByRole("link")).toHaveCount(0);
  await expect(categories.getByRole("listitem")).toHaveCount(6);
});
