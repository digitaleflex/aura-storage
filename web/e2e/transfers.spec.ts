import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Transfers console (breadth: queue shared with the files page, filters,
 * details, retry, pause/resume, confirmed cancellation).
 *
 * The API and the presigned endpoint are mocked: no real storage is contacted.
 * Only the browser behaviour is under test.
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

interface Mocks {
  calls: string[];
  intents: () => number;
  /** Let the next commit for the rejected file succeed. */
  disableFailure: () => void;
}

async function installMocks(
  page: Page,
  options: { failName?: string; putDelayMs?: number } = {},
): Promise<Mocks> {
  const calls: string[] = [];
  let intentCount = 0;
  const intentNames = new Map<string, string>();

  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path === "/api/v1/login" && method === "POST") {
      await route.fulfill({ json: { csrf_token: CSRF } });
      return;
    }
    if (path === "/api/v1/me") {
      await route.fulfill({ json: { ...ME, name: "admin", csrf_token: CSRF } });
      return;
    }
    if (path === "/api/v1/folders") {
      await route.fulfill({ json: { items: [] } });
      return;
    }
    if (path === "/api/v1/admin/usage") {
      await route.fulfill({
        json: {
          measured_at: 1_700_000_000,
          limits: {
            max_object_bytes: 5_368_709_120,
            max_pending_intents: 100,
            intent_ttl: 900,
            allow_empty_objects: false,
          },
          capacity: {
            capacity_bytes: 2_199_023_255_552,
            high_watermark_pct: 90,
            accept_until_bytes: 1_979_120_929_996,
            stored_bytes: 549_755_813_888,
            reserved_bytes: 0,
            free_for_uploads_bytes: 1_649_267_441_664,
          },
          totals: {
            objects_by_status: { available: 2 },
            available_count: 2,
            stored_bytes: 549_755_813_888,
          },
          spaces: [],
        },
      });
      return;
    }
    if (path === "/api/v1/objects" && method === "GET") {
      await route.fulfill({ json: { items: [] } });
      return;
    }
    if (path === "/api/v1/objects/upload-intents" && method === "POST") {
      intentCount += 1;
      const body = request.postDataJSON() as {
        display_name: string;
        size_bytes: number;
      };
      const id = `obj-${intentCount}`;
      intentNames.set(id, body.display_name);
      calls.push(`intent:${body.display_name}`);
      await route.fulfill({
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
      return;
    }
    const commit = path.match(/\/api\/v1\/objects\/([^/]+)\/commit$/);
    if (commit && method === "POST") {
      const id = decodeURIComponent(commit[1] ?? "");
      const intentName = intentNames.get(id);
      const failThis =
        options.failName !== undefined && intentName === options.failName;
      if (failThis) {
        calls.push(`commit-failed:${id}`);
        await route.fulfill({ status: 507, json: { detail: "storage full" } });
        return;
      }
      calls.push(`commit:${id}`);
      await route.fulfill({
        json: {
          id,
          status: "available",
          size_bytes: 11,
          checksum_sha256: "a".repeat(64),
        },
      });
      return;
    }
    if (/\/api\/v1\/objects\/[^/]+\/abort$/.test(path) && method === "POST") {
      calls.push("abort");
      await route.fulfill({ json: { id: "obj", status: "aborted", aborted: true } });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: `unmocked ${method} ${path}` } });
  });

  await page.route("**/fake-s3/**", async (route: Route) => {
    calls.push("put");
    if (options.putDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.putDelayMs));
    }
    await route.fulfill({ status: 200, body: "" }).catch(() => undefined);
  });

  return {
    calls,
    intents: () => intentCount,
    disableFailure: () => {
      options.failName = undefined;
    },
  };
}

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

async function goToTransfers(page: Page): Promise<void> {
  await page.getByRole("link", { name: "Transferts", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Transferts" })).toBeVisible();
}

async function seedFiles(page: Page, names: string[]): Promise<void> {
  await page.getByTestId("files-input").setInputFiles(
    names.map((name) => ({
      name,
      mimeType: name.endsWith(".png") ? "image/png" : "application/pdf",
      buffer: Buffer.from(`contenu ${name}`),
    })),
  );
  await page.getByRole("button", { name: "Importer et valider" }).click();
}

test("empty session points to the existing importer without inventing a transfer", async ({
  page,
}) => {
  await installMocks(page);
  await login(page);
  await goToTransfers(page);

  await expect(page.getByTestId("transfer-overview")).toContainText(
    "Aucune importation en cours",
  );
  await expect(page.getByText("Aucun transfert dans cette session")).toBeVisible();
  await expect(page.locator('[data-testid="transfer-row"]')).toHaveCount(0);

  await page.getByRole("button", { name: "Ajouter des fichiers" }).first().click();
  await page.waitForURL("/");
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
  await expect(page.locator("#intake")).toBeVisible();
});

test("shows the live queue, filters it, exposes details and retries a failure", async ({
  page,
}) => {
  const mocks = await installMocks(page, { failName: "rejete.pdf" });
  await login(page);
  await seedFiles(page, ["rapport.pdf", "capture.png", "rejete.pdf"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Disponible", {
    timeout: 15_000,
  });
  await expect(page.getByTestId("transfer-status")).toContainText("Échec");

  await goToTransfers(page);

  const rows = page.locator('[data-testid="transfer-row"]');
  await expect(rows).toHaveCount(3);
  await expect(page.locator('[data-status="completed"]')).toHaveCount(2);
  await expect(page.locator('[data-status="failed"]')).toHaveCount(1);
  await expect(page.getByTestId("transfer-overview")).toContainText("2 sur 3 fichiers terminés");
  await expect(page.locator('[data-testid="transfer-error-panel"]')).toBeVisible();

  // Status tabs carry real counters and match the filter.
  await page.getByRole("button", { name: /^Terminés/ }).click();
  await expect(rows).toHaveCount(2);
  await page.getByRole("button", { name: /^Échecs/ }).click();
  await expect(rows).toHaveCount(1);

  // Search resets to a readable subset and clears.
  await page.getByRole("searchbox", { name: "Rechercher un fichier" }).fill("capture");
  await page.getByTestId("transfer-filters").getByRole("button", { name: /^Tous/ }).click();
  await expect(rows).toHaveCount(1);
  await page.getByRole("button", { name: "Effacer la recherche" }).click();
  await expect(rows).toHaveCount(3);

  // Details show only engine fields (checksum, attempts, timeline).
  await page.getByRole("button", { name: "Actions pour rejete.pdf" }).click();
  await page.getByRole("menuitem", { name: "Détails" }).click();
  const details = page.getByTestId("transfer-details");
  await expect(details).toBeVisible();
  await expect(details).toContainText("Refus du serveur");
  await expect(details).toContainText("Étapes");
  await page.keyboard.press("Escape");

  // A retry goes through the engine and the row becomes completed.
  mocks.disableFailure();
  await page.getByRole("button", { name: "Nouvelle tentative" }).click();
  await expect(page.locator('[data-status="failed"]')).toHaveCount(0, {
    timeout: 15_000,
  });
  await expect(page.locator('[data-status="completed"]')).toHaveCount(3);
  // Retry opens a fresh submission (same idempotency key; the server dedupes).
  expect(mocks.intents()).toBe(4);
});

test("pause holds files that have not started and resume releases them", async ({ page }) => {
  await installMocks(page, { putDelayMs: 2500 });
  await login(page);
  await seedFiles(
    page,
    Array.from({ length: 8 }, (_, index) => `lot-${index}.pdf`),
  );

  await goToTransfers(page);
  await page.getByRole("button", { name: "Pause tous les transferts" }).click();
  await expect(page.locator('[data-status="paused"]').first()).toBeVisible();

  await page.getByRole("button", { name: "Reprendre", exact: true }).click();
  await expect(
    page.getByTestId("transfer-overview").getByText("Importation terminée"),
  ).toBeVisible({ timeout: 25_000 });
  await expect(page.locator('[data-status="completed"]')).toHaveCount(8);
});

test("cancel all asks for confirmation and aborts the backend intents", async ({ page }) => {
  const mocks = await installMocks(page, { putDelayMs: 3000 });
  await login(page);
  await seedFiles(page, ["lent-a.pdf", "lent-b.pdf"]);
  await goToTransfers(page);

  await page.getByRole("button", { name: "Annuler tout" }).click();
  const dialog = page.getByTestId("transfer-cancel-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Les fichiers déjà vérifiés");
  expect(mocks.calls).not.toContain("abort");

  await page.getByRole("button", { name: "Tout annuler" }).click();
  await expect.poll(() => mocks.calls.filter((call) => call === "abort").length).toBeGreaterThan(0);
  await expect(page.locator('[data-status="cancelled"]')).toHaveCount(2, {
    timeout: 10_000,
  });
  expect(mocks.calls.some((call) => call.startsWith("commit:"))).toBe(false);
});

test("advanced filters narrow the list and the empty result stays distinct", async ({
  page,
}) => {
  await installMocks(page);
  await login(page);
  await seedFiles(page, ["rapport.pdf", "capture.png", "archive.zip"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Disponible", {
    timeout: 15_000,
  });
  await goToTransfers(page);

  const rows = page.locator('[data-testid="transfer-row"]');
  await expect(rows).toHaveCount(3);

  await page.getByRole("button", { name: "Filtres", exact: true }).click();
  await page.getByLabel("Type de fichier").selectOption("image");
  await expect(rows).toHaveCount(1);
  await expect(page.locator('[data-testid="transfer-row"]')).toContainText("capture.png");

  await page.getByLabel("Taille min. (Mo)").fill("1");
  await expect(rows).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Aucun fichier ne correspond à ces filtres" }),
  ).toBeVisible();
  // Not the empty-session state.
  await expect(page.getByText("Aucun transfert dans cette session")).toHaveCount(0);

  await page.getByRole("button", { name: "Réinitialiser", exact: true }).click();
  await expect(rows).toHaveCount(3);

  // Selection is explicit and reversible.
  await page.getByRole("checkbox", { name: "Sélectionner tous les transferts filtrés" }).check();
  await expect(page.getByText("3 sélectionnés")).toBeVisible();
  await page.getByRole("button", { name: "Désélectionner" }).click();
  await expect(page.getByText("3 sélectionnés")).toHaveCount(0);
});

test("lot A — titre, position dans la file, annulation détaillée et sélection par statut", async ({
  page,
}) => {
  await installMocks(page, { failName: "rejete.pdf", putDelayMs: 1200 });
  await login(page);
  await seedFiles(page, [
    "a.pdf",
    "b.pdf",
    "rejete.pdf",
    "d.pdf",
    "e.pdf",
    "f.pdf",
    "g.pdf",
    "h.pdf",
  ]);
  await goToTransfers(page);

  await expect.poll(() => page.title()).toMatch(/^\(\d+\) Transferts/);
  await expect(page.getByText(/dans la file/).first()).toBeVisible();

  await page.getByRole("button", { name: "Annuler tout" }).click();
  const dialog = page.getByTestId("transfer-cancel-dialog");
  await expect(dialog).toContainText(/en cours/);
  await expect(dialog).toContainText(/en attente/);
  await expect(dialog).toContainText("déjà vérifié");
  await page.getByRole("button", { name: "Retour" }).click();

  await page.getByRole("button", { name: "Plus d'actions sur les transferts" }).click();
  await page
    .getByRole("menuitem", { name: /Sélectionner les fichiers en attente/ })
    .click();
  await expect(page.locator(".transfers-bulk-count")).toBeVisible();

  await expect(page.getByTestId("transfer-overview")).toContainText(
    "Importation terminée",
    { timeout: 25_000 },
  );
  await expect.poll(() => page.title()).toContain("échec");
});

test("lot A — copier le nom et le message d'erreur", async ({ page }) => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await installMocks(page, { failName: "rejete.pdf" });
  await login(page);
  await seedFiles(page, ["ok.pdf", "rejete.pdf"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Échec", {
    timeout: 15_000,
  });
  await goToTransfers(page);

  await page.getByRole("button", { name: "Copier l'erreur" }).click();
  const errorClipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(errorClipboard).toContain("rejete.pdf");
  expect(errorClipboard).toContain("refusé");

  await page.getByRole("button", { name: "Actions pour rejete.pdf" }).click();
  await page.getByRole("menuitem", { name: "Détails" }).click();
  await page.getByRole("button", { name: "Copier le nom" }).click();
  const nameClipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(nameClipboard).toBe("rejete.pdf");
});

test("lot A — le plateau mène à la console sans interrompre la file", async ({ page }) => {
  await installMocks(page, { putDelayMs: 2000 });
  await login(page);
  await seedFiles(page, ["un.pdf", "deux.pdf"]);

  await page.getByRole("link", { name: "Voir tous les transferts" }).click();
  await page.waitForURL("/transfers");
  await expect(page.locator('[data-testid="transfer-row"]')).toHaveCount(2);
  await expect(page.getByTestId("transfer-overview")).toContainText("Importation en cours");
});

test("lot A — bandeau hors-ligne puis reprise au retour du réseau", async ({ page }) => {
  await installMocks(page, { putDelayMs: 3000 });
  await login(page);
  await seedFiles(page, ["net-a.pdf", "net-b.pdf", "net-c.pdf", "net-d.pdf"]);
  await goToTransfers(page);
  await expect(page.getByText("Connexion perdue")).toHaveCount(0);

  await page.context().setOffline(true);
  await expect(page.getByText("Connexion perdue", { exact: true })).toBeVisible();

  await page.context().setOffline(false);
  await expect(page.getByText("Connexion perdue", { exact: true })).toHaveCount(0, {
    timeout: 10_000,
  });
});

test("lot A — en-tête de liste sticky pendant le défilement", async ({ page }) => {
  await installMocks(page);
  await login(page);
  await seedFiles(
    page,
    Array.from({ length: 30 }, (_, index) => `sticky-${index}.pdf`),
  );
  await expect(page.getByTestId("transfer-status")).toContainText("30", {
    timeout: 20_000,
  });
  await goToTransfers(page);
  await expect(page.locator('[data-testid="transfer-row"]')).toHaveCount(30);

  const header = page.locator(".transfers-table thead th").first();
  await page.evaluate(() => window.scrollTo(0, 1200));
  await page.waitForTimeout(200);
  const box = await header.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y).toBeGreaterThanOrEqual(55);
  expect(box!.y).toBeLessThanOrEqual(70);
});

test("lot B — filtres dans l'URL, retour arrière et valeurs partageables", async ({
  page,
}) => {
  await installMocks(page, { failName: "rejete.pdf" });
  await login(page);
  await seedFiles(page, ["a.pdf", "capture.png", "rejete.pdf"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Échec", {
    timeout: 15_000,
  });
  await goToTransfers(page);
  const rows = page.locator('[data-testid="transfer-row"]');

  await page.getByTestId("transfer-filters").getByRole("button", { name: /^Échecs/ }).click();
  await expect(page).toHaveURL(/status=failed/);
  await expect(rows).toHaveCount(1);

  await page.goBack();
  await expect(page).not.toHaveURL(/status=failed/);
  await expect(rows).toHaveCount(3);

  await page.getByRole("searchbox", { name: "Rechercher un fichier" }).fill("capture");
  await expect.poll(() => page.url()).toContain("q=capture");
  await expect(rows).toHaveCount(1);

  // A shared URL restores the filters on a fresh page load (session queue is
  // empty then, but the controls must reflect the URL).
  await page.goto("/transfers?status=failed&q=rejete");
  await expect(
    page.getByTestId("transfer-filters").getByRole("button", { name: /^Échecs/ }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("searchbox", { name: "Rechercher un fichier" })).toHaveValue(
    "rejete",
  );
});

test("lot B — la ligne terminee ou en echec est brievement surlignee", async ({ page }) => {
  await installMocks(page, { failName: "bad.pdf", putDelayMs: 3000 });
  await login(page);
  await seedFiles(page, ["bad.pdf"]);
  await goToTransfers(page);

  await expect(page.locator('[data-highlight="danger"]')).toHaveCount(1, {
    timeout: 10_000,
  });
  await expect(page.locator('[data-highlight="danger"]')).toHaveCount(0, {
    timeout: 3000,
  });
});

test("lot B — horodatage d'ajout, duree, debit moyen et sparkline", async ({
  page,
}) => {
  await installMocks(page, { putDelayMs: 1500 });
  await login(page);
  await seedFiles(page, [
    "b-1.pdf",
    "b-2.pdf",
    "b-3.pdf",
    "b-4.pdf",
    "b-5.pdf",
    "b-6.pdf",
  ]);
  await goToTransfers(page);

  // Even a file that has not started keeps a first-seen timestamp.
  await expect(
    page.locator('[data-status="queued"]').first().getByText(/Ajouté à/),
  ).toBeVisible();

  await expect(page.getByText(/Durée \d+:\d+/)).toBeVisible();
  await expect(page.getByText(/Débit moyen/)).toBeVisible();
  await expect(page.locator(".transfers-sparkline")).toBeVisible({ timeout: 10_000 });

  await expect(page.getByTestId("transfer-overview")).toContainText(
    "Importation terminée",
    { timeout: 25_000 },
  );
  await expect(page.getByText(/Durée \d+:\d+/)).toBeVisible();
});

test("lot C — tri par clic sur l'entete et dans l'URL", async ({ page }) => {
  await installMocks(page);
  await login(page);
  await seedFiles(page, ["zeta.pdf", "alpha.pdf", "moyen.pdf"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Disponible", {
    timeout: 15_000,
  });
  await goToTransfers(page);
  const rows = page.locator('[data-testid="transfer-row"]');

  await page.getByRole("button", { name: /Nom du fichier/ }).click();
  await expect(rows.first().getByText("alpha.pdf")).toBeVisible();
  await expect(
    page.getByRole("columnheader", { name: /Nom du fichier/ }),
  ).toHaveAttribute("aria-sort", "ascending");
  await expect(page).toHaveURL(/sort=name/);

  await page.getByRole("button", { name: /Nom du fichier/ }).click();
  await expect(rows.first().getByText("zeta.pdf")).toBeVisible();
  await expect(
    page.getByRole("columnheader", { name: /Nom du fichier/ }),
  ).toHaveAttribute("aria-sort", "descending");
  await expect(page).toHaveURL(/dir=desc/);
});

test("lot C — colonnes adaptatives sans debordement horizontal", async ({ page }) => {
  await installMocks(page);
  await login(page);
  await seedFiles(page, ["a.pdf", "b.pdf", "c.pdf"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Disponible", {
    timeout: 15_000,
  });
  await goToTransfers(page);

  for (const width of [1280, 1100, 950, 768]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(150);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
    if (width <= 1150) {
      await expect(page.locator("th.transfers-col-speed")).toBeHidden();
    } else {
      await expect(page.locator("th.transfers-col-speed")).toBeVisible();
    }
    if (width <= 1000 && width > 760) {
      await expect(page.locator("th.transfers-col-size")).toBeHidden();
    }
  }
});

test("lot C — bandeau de reprise apres un import interrompu", async ({ page }) => {
  await installMocks(page);
  await login(page);
  // Simulate a journal left behind by an interrupted import (no live queue).
  await page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("aura-upload-journal", 1);
      request.onupgradeneeded = () => {
        const store = request.result.createObjectStore("files", { keyPath: "key" });
        store.createIndex("owner", "owner");
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await new Promise<void>((resolve) => {
      const tx = db.transaction("files", "readwrite");
      const store = tx.objectStore("files");
      store.put({
        key: "k1",
        owner: "u1",
        rel: "reprise-a.pdf",
        size: 1024,
        folderId: null,
        idempotencyKey: "i1",
      });
      store.put({
        key: "k2",
        owner: "u1",
        rel: "reprise-b.pdf",
        size: 2048,
        folderId: null,
        idempotencyKey: "i2",
      });
      tx.oncomplete = () => resolve();
    });
  });

  await goToTransfers(page);
  await expect(page.getByText("Import interrompu")).toBeVisible();
  await expect(page.getByText("2 fichiers")).toBeVisible();
  await page.getByRole("button", { name: "Reprendre l'import" }).click();
  await page.waitForURL("/");
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
  await expect(page.locator("#intake")).toBeVisible();
});

test("lot C — export CSV de la vue", async ({ page }) => {
  const fs = await import("node:fs");
  await installMocks(page);
  await login(page);
  await seedFiles(page, ["rapport.pdf", "a;b.pdf"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Disponible", {
    timeout: 15_000,
  });
  await goToTransfers(page);
  await expect(page.locator('[data-testid="transfer-row"]')).toHaveCount(2);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Plus d'actions sur les transferts" }).click();
  await page.getByRole("menuitem", { name: /Exporter la vue/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^aura-transferts-\d{8}\d{4}\.csv$/);
  const path = await download.path();
  const content = fs.readFileSync(path!, "utf8");
  expect(content.startsWith("\ufeff")).toBe(true);
  expect(content).toContain("Nom;Taille (octets);Transféré (octets);Statut;Tentatives;Type d'échec;Message d'erreur;Ajouté le;Dernier changement");
  expect(content).toContain('"a;b.pdf"');
});

test("lot C — virtualisation d'un gros lot", async ({ page }) => {
  await installMocks(page);
  await login(page);
  await seedFiles(page, Array.from({ length: 250 }, (_, index) => `sticky-${index}.pdf`));
  await expect(page.getByTestId("transfer-status")).toContainText("250", {
    timeout: 30_000,
  });
  await goToTransfers(page);
  const list = page.getByTestId("transfer-list");
  await expect(list).toHaveAttribute("data-virtualized", "true");
  const rendered = await page.locator('[data-testid="transfer-row"]').count();
  expect(rendered).toBeLessThan(100);
  expect(rendered).toBeGreaterThan(0);

  await page.locator('[data-testid="transfer-list"]').evaluate((el) => el.scrollTo(0, el.scrollHeight));
  await page.waitForTimeout(500);
  await expect(page.getByText("sticky-249.pdf")).toBeVisible();

  await page.locator('[data-testid="transfer-list"]').evaluate((el) => el.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await expect(page.getByText("sticky-0.pdf")).toBeVisible();
});

test("lot E — snapshot de diagnostic telechargeable pour un echec", async ({ page }) => {
  const fs = await import("node:fs");
  await installMocks(page, { failName: "bad.pdf" });
  await login(page);
  await seedFiles(page, ["bad.pdf"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Échec", {
    timeout: 15_000,
  });
  await goToTransfers(page);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Télécharger le diagnostic" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^aura-diagnostic-.+\.json$/);
  const path = await download.path();
  const diagnostic = JSON.parse(fs.readFileSync(path!, "utf8"));
  expect(diagnostic.schema).toBe("aura.transfer-diagnostic/v1");
  expect(diagnostic.reportId).toBeTruthy();
  expect(diagnostic.file.name).toBe("bad.pdf");
  expect(diagnostic.transfer.status).toBe("failed");
  expect(diagnostic.transfer.failureKind).toBe("fatal");
  expect(diagnostic.transfer.phaseLog.length).toBeGreaterThan(0);
  expect(JSON.stringify(diagnostic)).not.toMatch(/https?:\/\//);
});

test("lot E — diagnostic de session avec reprise et concurrence", async ({ page }) => {
  const fs = await import("node:fs");
  await installMocks(page);
  await login(page);
  await seedFiles(page, ["s-1.pdf", "s-2.pdf"]);
  await expect(page.getByTestId("transfer-status")).toContainText("Disponible", {
    timeout: 15_000,
  });
  await goToTransfers(page);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Plus d'actions sur les transferts" }).click();
  await page.getByRole("menuitem", { name: "Télécharger le diagnostic de session" }).click();
  const download = await downloadPromise;
  const path = await download.path();
  const diagnostic = JSON.parse(fs.readFileSync(path!, "utf8"));
  expect(diagnostic.schema).toBe("aura.transfer-session-diagnostic/v1");
  expect(diagnostic.items).toHaveLength(2);
  // The rate-aware ramp starts at one stream: the configured ceiling is still
  // reported, but the effective width is only allowed to be within it.
  expect(diagnostic.session.maxConcurrency).toBe(4);
  expect(diagnostic.session.concurrency).toBeGreaterThanOrEqual(1);
  expect(diagnostic.session.concurrency).toBeLessThanOrEqual(4);
  expect(Array.isArray(diagnostic.session.rateHistoryBytesPerSecond)).toBe(true);
  expect(diagnostic.environment.userAgent).toBeTruthy();
});

test("visual baseline — completed session", async ({ page }) => {
  test.skip(!!process.env.CI, "visual baselines are reference-host specific");
  await installMocks(page, { failName: "archive.zip" });
  await login(page);
  await seedFiles(page, [
    "presentation-client.pdf",
    "photo-produit.png",
    "archive.zip",
    "budget-2026.xlsx",
  ]);
  await expect(page.getByTestId("transfer-status")).toContainText("Échec", {
    timeout: 15_000,
  });
  await goToTransfers(page);
  await expect(page.getByTestId("transfer-overview")).toContainText(
    "Importation terminée",
  );
  await page.waitForTimeout(300);

  const masks = [
    page.locator(".transfers-file-meta"),
    page.locator(".transfers-toolbar-hint"),
    page.locator(".visually-hidden"),
  ];

  await expect(page).toHaveScreenshot("transfers-desktop.png", {
    fullPage: false,
    maxDiffPixels: 300,
    mask: masks,
  });

  await page.setViewportSize({ width: 375, height: 667 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await expect(page).toHaveScreenshot("transfers-mobile.png", {
    fullPage: false,
    maxDiffPixels: 300,
    mask: masks,
  });
});
