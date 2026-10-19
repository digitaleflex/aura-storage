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
 *  5. the import panel opens on demand and states the server-side check.
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
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
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
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
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

// -- 5. on-demand import panel ----------------------------------------------

test("the import panel opens on demand and states the server-side check", async ({
  page,
}) => {
  await installMocks(page);
  await login(page);

  const intake = page.getByRole("region", { name: "Importer" });
  // Closed by default: the register is the first thing on the page.
  await expect(intake).toBeHidden();

  await page.getByRole("button", { name: "Importer", exact: true }).click();
  await expect(intake).toBeVisible();
  await expect(intake).toContainText("SHA-256");
  await expect(
    intake.getByRole("button", { name: "Importer et valider" }),
  ).toBeDisabled();

  // Closing it (nothing pending) hides it again.
  await intake.getByRole("button", { name: "Fermer" }).click();
  await expect(intake).toBeHidden();
});

// -- 6. recursive (cascade) folder deletion ---------------------------------
//
// The server refuses a non-empty folder with 409. These tests drive the
// front-end cascade: a real listing of the subtree, a typed confirmation, an
// explicit execution (files first, folders from the leaves up), a live "n/m"
// counter and a per-item failure log with Retry.

interface CascadeFolderItem {
  id: string;
  name: string;
  parent_id: string | null;
  created_at: number;
}

interface CascadeObjectItem {
  id: string;
  display_name: string;
  folder_id: string | null;
  content_type?: string;
  size_bytes?: number;
}

interface CascadeOptions {
  role?: string;
  scopes?: string[];
  folders: CascadeFolderItem[];
  objects: CascadeObjectItem[];
  /** Object id -> DELETEs that answer 500 before succeeding (transient fault). */
  objectFailures?: Record<string, number>;
  /** Folder id -> DELETEs that answer 500 before succeeding (transient fault). */
  folderFailures?: Record<string, number>;
}

interface CascadeMocks {
  /** Successful deletes in request order: "object:<id>" / "folder:<id>". */
  deletedOrder: () => string[];
}

/**
 * A mock with mutable, internally-consistent state: DELETE /folders enforces
 * the real "not empty" rule, so a cascade that deletes in the wrong order
 * would fail here exactly as it would against the API.
 */
async function installCascadeMocks(
  page: Page,
  options: CascadeOptions,
): Promise<CascadeMocks> {
  const folders = [...options.folders];
  const objects = [...options.objects];
  const objectFailures = { ...(options.objectFailures ?? {}) };
  const folderFailures = { ...(options.folderFailures ?? {}) };
  const deleted: string[] = [];
  const scopes = options.scopes ?? [
    "objects:read",
    "objects:write",
    "objects:delete",
    "objects:purge",
  ];

  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/v1/login" && method === "POST") {
      await route.fulfill({ json: { csrf_token: CSRF } });
      return;
    }
    if (path === "/api/v1/me") {
      await route.fulfill({
        json: {
          id: "u1",
          kind: "user",
          role: options.role ?? "admin",
          space_id: "s1",
          application_id: "a1",
          scopes,
        },
      });
      return;
    }
    if (path === "/api/v1/folders" && method === "GET") {
      await route.fulfill({ json: { items: folders } });
      return;
    }
    const folderDelete = path.match(/^\/api\/v1\/folders\/([^/]+)$/);
    if (folderDelete && method === "DELETE") {
      const id = decodeURIComponent(folderDelete[1] ?? "");
      if ((folderFailures[id] ?? 0) > 0) {
        folderFailures[id] = (folderFailures[id] ?? 0) - 1;
        await route.fulfill({ status: 500, json: { detail: "transient failure" } });
        return;
      }
      const hasChildren = folders.some((folder) => folder.parent_id === id);
      const hasObjects = objects.some((object) => object.folder_id === id);
      if (hasChildren || hasObjects) {
        await route.fulfill({ status: 409, json: { detail: "folder is not empty" } });
        return;
      }
      const index = folders.findIndex((folder) => folder.id === id);
      if (index >= 0) folders.splice(index, 1);
      deleted.push(`folder:${id}`);
      await route.fulfill({ json: { id, status: "deleted" } });
      return;
    }
    const objectDelete = path.match(/^\/api\/v1\/objects\/([^/]+)$/);
    if (objectDelete && method === "DELETE") {
      const id = decodeURIComponent(objectDelete[1] ?? "");
      if ((objectFailures[id] ?? 0) > 0) {
        objectFailures[id] = (objectFailures[id] ?? 0) - 1;
        await route.fulfill({ status: 500, json: { detail: "transient failure" } });
        return;
      }
      const index = objects.findIndex((object) => object.id === id);
      if (index >= 0) objects.splice(index, 1);
      deleted.push(`object:${id}`);
      await route.fulfill({ json: { id, status: "deleted" } });
      return;
    }
    if (path === "/api/v1/objects" && method === "GET") {
      const folderParam = url.searchParams.get("folder_id");
      const limit = Number(url.searchParams.get("limit") ?? "50");
      const offset = Number(url.searchParams.get("offset") ?? "0");
      const filtered =
        folderParam === null
          ? objects
          : objects.filter(
              (object) => (object.folder_id ?? "root") === folderParam,
            );
      await route.fulfill({
        json: {
          items: filtered.slice(offset, offset + limit).map((object) => ({
            id: object.id,
            display_name: object.display_name,
            content_type: object.content_type ?? "application/pdf",
            size_bytes: object.size_bytes ?? 11,
            checksum_sha256: "abc",
            status: "available",
            folder_id: object.folder_id,
            created_at: 0,
            updated_at: 0,
          })),
        },
      });
      return;
    }
    if (path === "/api/v1/admin/usage" && method === "GET") {
      await route.fulfill({ json: USAGE });
      return;
    }
    await route.fulfill({
      status: 404,
      json: { detail: `unmocked ${method} ${path}` },
    });
  });

  return { deletedOrder: () => [...deleted] };
}

const CASCADE_FOLDERS: CascadeFolderItem[] = [
  { id: "f-1", name: "Photos", parent_id: null, created_at: 0 },
  { id: "f-2", name: "2023", parent_id: "f-1", created_at: 0 },
  { id: "f-3", name: "raw", parent_id: "f-2", created_at: 0 },
];

const CASCADE_OBJECTS: CascadeObjectItem[] = [
  { id: "obj-r1", display_name: "racine.jpg", folder_id: "f-1" },
  { id: "obj-23", display_name: "a.jpg", folder_id: "f-2" },
  { id: "obj-raw", display_name: "b.raw", folder_id: "f-3" },
];

/** Files first, then folders from the leaves up to the target. */
const CASCADE_EXPECTED_ORDER = [
  "object:obj-r1",
  "object:obj-23",
  "object:obj-raw",
  "folder:f-3",
  "folder:f-2",
  "folder:f-1",
];

const CASCADE_OPTION_LABEL =
  "Supprimer aussi tout son contenu (fichiers et sous-dossiers)";

test("a 409 folder deletion can cascade: content listed, confirmed, deleted leaves-to-root", async ({
  page,
}) => {
  const mocks = await installCascadeMocks(page, {
    folders: CASCADE_FOLDERS,
    objects: CASCADE_OBJECTS,
  });
  await login(page);

  const photos = page.getByRole("button", { name: "Photos", exact: true });
  await expect(photos).toBeVisible();

  // A plain delete is refused: the folder still holds files and subfolders.
  await page.getByRole("button", { name: "Actions pour le dossier Photos" }).click();
  await page.getByRole("menuitem", { name: "Supprimer" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Supprimer" }).click();
  const refusal = page.getByRole("alert").filter({ hasText: "n'est pas vide" });
  await expect(refusal).toBeVisible();

  // The refusal offers the explicit recursive flow.
  await refusal
    .getByRole("button", { name: "Supprimer avec son contenu…" })
    .click();

  const dialog = page.getByRole("dialog", {
    name: "Supprimer le dossier et son contenu",
  });
  await expect(dialog).toBeVisible();
  // The inventory comes from real list requests (3 files, 2 subfolders).
  await expect(dialog.getByText("3 fichier(s)", { exact: true })).toBeVisible();
  await expect(
    dialog.getByText("2 sous-dossier(s)", { exact: true }),
  ).toBeVisible();

  // Nothing runs until the folder name is typed back.
  const run = dialog.getByRole("button", {
    name: "Supprimer le contenu et le dossier",
  });
  await expect(run).toBeDisabled();
  await dialog.getByLabel("Confirmation par recopie du nom").fill("Photos");
  await expect(run).toBeEnabled();
  await run.click();

  await expect(
    dialog.getByText(/Contenu supprimé et dossier supprimé/),
  ).toBeVisible();
  expect(mocks.deletedOrder()).toEqual(CASCADE_EXPECTED_ORDER);

  // The explorer refreshes to the real state: the folder is gone.
  await dialog.getByRole("button", { name: "Fermer" }).click();
  await expect(photos).toHaveCount(0);
});

test("a partial cascade failure is logged and retried to completion", async ({
  page,
}) => {
  const mocks = await installCascadeMocks(page, {
    folders: CASCADE_FOLDERS,
    objects: CASCADE_OBJECTS,
    // The leaf folder's first DELETE fails once (transient server fault).
    folderFailures: { "f-3": 1 },
  });
  await login(page);

  // Reach the cascade directly from the folder confirmation dialog.
  await page.getByRole("button", { name: "Actions pour le dossier Photos" }).click();
  await page.getByRole("menuitem", { name: "Supprimer" }).click();
  const confirmDialog = page.getByRole("dialog");
  await confirmDialog.getByLabel(CASCADE_OPTION_LABEL).check();
  await confirmDialog.getByRole("button", { name: "Supprimer" }).click();

  const dialog = page.getByRole("dialog", {
    name: "Supprimer le dossier et son contenu",
  });
  await dialog.getByLabel("Confirmation par recopie du nom").fill("Photos");
  await dialog
    .getByRole("button", { name: "Supprimer le contenu et le dossier" })
    .click();

  // A leaf folder fails, so its parents cannot be deleted either: real
  // failures, each logged by item — never a fabricated success.
  await expect(
    dialog.getByText(/Suppression terminée avec échecs/),
  ).toBeVisible();
  await expect(
    dialog.getByRole("heading", { name: /Journal des échecs/ }),
  ).toBeVisible();
  await expect(dialog.getByText("raw", { exact: true })).toBeVisible();

  // Retrying the failures completes the deletion.
  await dialog.getByRole("button", { name: "Réessayer les échecs" }).click();
  await expect(
    dialog.getByText(/Contenu supprimé et dossier supprimé/),
  ).toBeVisible();
  await expect(
    dialog.getByRole("heading", { name: /Journal des échecs/ }),
  ).toHaveCount(0);
  expect(mocks.deletedOrder()).toEqual(CASCADE_EXPECTED_ORDER);
});

test("the cascade option is only offered with objects:delete + objects:write", async ({
  page,
}) => {
  await installCascadeMocks(page, {
    role: "user",
    scopes: ["objects:read", "objects:write"],
    folders: [{ id: "f-1", name: "Photos", parent_id: null, created_at: 0 }],
    objects: [{ id: "obj-1", display_name: "a.jpg", folder_id: "f-1" }],
  });
  await login(page, "user");

  // The folder confirmation never offers a flow this session may not run.
  await page.getByRole("button", { name: "Actions pour le dossier Photos" }).click();
  await page.getByRole("menuitem", { name: "Supprimer" }).click();
  const confirmDialog = page.getByRole("dialog");
  await expect(confirmDialog.getByLabel(CASCADE_OPTION_LABEL)).toHaveCount(0);
  await confirmDialog.getByRole("button", { name: "Supprimer" }).click();

  // The 409 refusal stays, but without the cascade entry point.
  const refusal = page.getByRole("alert").filter({ hasText: "n'est pas vide" });
  await expect(refusal).toBeVisible();
  await expect(
    refusal.getByRole("button", { name: "Supprimer avec son contenu…" }),
  ).toHaveCount(0);
});
