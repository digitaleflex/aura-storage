import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

/**
 * Admin Storage maintenance flows, with a fully mocked management API.
 *
 * These are browser-level safety checks: no maintenance request is sent before
 * confirmation, destructive commands carry CSRF, results (including reverify's
 * diagnostic 409) are readable, and admin:read alone never reveals a command.
 * No real catalogue or storage is touched.
 */

const CSRF = "csrf-maintenance";
const OBJECT_ID = "11111111-1111-4111-8111-111111111111";
const SPACE_ID = "22222222-2222-4222-8222-222222222222";
const BUCKET = "aura-test";

interface MaintenanceCall {
  path: string;
  method: string;
  body: unknown;
  csrf: string | undefined;
}

interface Options {
  canWrite?: boolean;
  reverifyStatuses?: number[];
  terminalStatus?: number;
  scrubStatus?: number;
  reverseStatus?: number;
  cleanupStatuses?: number[];
  keepOrphansAfterCleanup?: boolean;
  largeOrphanScan?: boolean;
  nextScanStatuses?: number[];
}

const INTEGRITY = {
  interval_days: 30,
  results: {
    ok: { count: 8, oldest: 1_700_000_000 },
    unchecked: { count: 1, oldest: null },
    mismatch: { count: 1, oldest: 1_700_000_100 },
    missing: { count: 0, oldest: null },
  },
  problems: [{
    id: OBJECT_ID,
    space_id: SPACE_ID,
    display_name: "contrat.pdf",
    size_bytes: 12,
    scrub_result: "mismatch",
    scrubbed_at: 1_700_000_100,
  }],
};

const STORAGE_ORPHANS = {
  grace_seconds: 86400,
  checked_at: 1_700_000_000,
  buckets: [{
    bucket: BUCKET,
    scanned: 120,
    orphan_bytes: 8,
    orphans: [
      { key: "aura/stray-1", size_bytes: 5, last_modified: 1, reason: "no_row", object_id: null },
      { key: "aura/stray-2", size_bytes: 3, last_modified: 1, reason: "terminal", object_id: "old-object" },
    ],
    stale_uploads: [{ key: "aura/partial", upload_id: "upload-1", initiated: 1 }],
    next_start_after: "aura/stray-2",
  }],
};

const EMPTY_STORAGE_ORPHANS = {
  grace_seconds: 86400,
  checked_at: 1_700_000_100,
  buckets: [{ bucket: BUCKET, scanned: 120, orphan_bytes: 0, orphans: [], stale_uploads: [] }],
};

const LARGE_STORAGE_ORPHANS = {
  grace_seconds: 86400,
  checked_at: 1_700_000_000,
  buckets: [{
    bucket: BUCKET,
    scanned: 101,
    orphan_bytes: 101,
    orphans: Array.from({ length: 101 }, (_, index) => ({
      key: `aura/stray-${String(index).padStart(3, "0")}`,
      size_bytes: 1,
      last_modified: 1,
      reason: "no_row",
      object_id: null,
    })),
    stale_uploads: [],
    next_start_after: null,
  }],
};

async function installMocks(page: Page, options: Options = {}) {
  const calls: MaintenanceCall[] = [];
  const scanCalls: string[] = [];
  const canWrite = options.canWrite ?? true;
  const reverifyStatuses = [...(options.reverifyStatuses ?? [200])];
  const cleanupStatuses = [...(options.cleanupStatuses ?? [200])];
  const nextScanStatuses = [...(options.nextScanStatuses ?? [200])];
  let cleaned = false;

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
          id: "admin-1",
          kind: "user",
          name: "admin",
          role: canWrite ? "admin" : "operator",
          space_id: SPACE_ID,
          application_id: "app-1",
          scopes: canWrite ? ["admin:read", "admin:write"] : ["admin:read"],
          csrf_token: CSRF,
        },
      });
      return;
    }
    if (path === "/api/v1/admin/stats") {
      await route.fulfill({ json: {
        objects_by_status: { available: 9 },
        applications: 0, spaces: 0, buckets: 1,
        service_identities: 0, active_service_identities: 0,
      } });
      return;
    }
    if ([
      "/api/v1/admin/applications",
      "/api/v1/admin/spaces",
      "/api/v1/admin/buckets",
      "/api/v1/admin/identities",
      "/api/v1/admin/partner-sites",
    ].includes(path)) {
      await route.fulfill({ json: { items: [] } });
      return;
    }
    if (path === "/api/v1/admin/usage") {
      await route.fulfill({ json: {
        measured_at: 1_700_000_000,
        period: "2026-11",
        limits: { max_object_bytes: 0, max_pending_intents: 0, intent_ttl: 0, allow_empty_objects: false },
        totals: { objects_by_status: { available: 9 }, available_count: 9, stored_bytes: 0, egress_bytes_month: 0 },
        spaces: [],
      } });
      return;
    }
    if (path === "/api/v1/admin/health") {
      await route.fulfill({ json: {
        status: "ok", checked_at: 1_700_000_000, components: {},
        recent_errors: { window_s: 3600, events: [], scanned: 0 }, note: "Test",
      } });
      return;
    }
    if (path === "/api/v1/admin/orphans") {
      await route.fulfill({ json: { checked: 0, candidates: [], checked_at: 1_700_000_000 } });
      return;
    }
    if (path === "/api/v1/admin/integrity") {
      await route.fulfill({ json: INTEGRITY });
      return;
    }
    if (path === "/api/v1/admin/storage-orphans") {
      scanCalls.push(request.url());
      const cursor = url.searchParams.get("start_after");
      if (cursor) {
        const status = nextScanStatuses.shift() ?? 200;
        if (status !== 200) {
          await route.fulfill({ status, json: { detail: "storage unavailable" } });
          return;
        }
        await route.fulfill({ json: {
          grace_seconds: 86400,
          checked_at: 1_700_000_100,
          buckets: [{
            bucket: BUCKET,
            scanned: 1,
            orphan_bytes: 4,
            orphans: [{ key: "aura/stray-3", size_bytes: 4, last_modified: 1, reason: "no_row", object_id: null }],
            stale_uploads: [{ key: "aura/partial", upload_id: "upload-1", initiated: 1 }],
            next_start_after: null,
          }],
        } });
        return;
      }
      const report = options.largeOrphanScan ? LARGE_STORAGE_ORPHANS : STORAGE_ORPHANS;
      await route.fulfill({
        json: cleaned && !options.keepOrphansAfterCleanup ? EMPTY_STORAGE_ORPHANS : report,
      });
      return;
    }
    if (path === "/api/v1/admin/audit") {
      await route.fulfill({ json: {
        items: [], total: 0, truncated: false, scanned: 0,
        retention_days: 90, queried_at: 1_700_000_000,
      } });
      return;
    }
    if (path === "/api/v1/admin/cover-candidates") {
      await route.fulfill({ json: {
        generated_at: null, counts: { books: 0, with_candidates: 0, candidates: 0 }, books: [],
      } });
      return;
    }

    if (method === "POST" && path.startsWith("/api/v1/admin/")) {
      calls.push({
        path: `${path}${url.search}`,
        method,
        body: request.postData() ? request.postDataJSON() : undefined,
        csrf: request.headers()["x-csrf-token"],
      });
      if (path === "/api/v1/admin/integrity/scrub") {
        const status = options.scrubStatus ?? 200;
        await route.fulfill({
          status,
          json: status === 200
            ? { ok: 2, mismatch: 1, missing: 0, error: 0, bytes: 4096 }
            : { detail: "storage unavailable" },
        });
        return;
      }
      if (path === `/api/v1/admin/objects/${OBJECT_ID}/reverify`) {
        const status = reverifyStatuses.shift() ?? 200;
        await route.fulfill({
          status,
          json: status === 409
            ? {
                id: OBJECT_ID, status: "suspect", reason: "checksum_mismatch",
                size_bytes: 12, checksum_sha256: "b".repeat(64),
              }
            : status === 200
              ? {
                  id: OBJECT_ID, status: "available", size_bytes: 12,
                  checksum_sha256: "a".repeat(64),
                }
              : { detail: "storage unavailable" },
        });
        return;
      }
      if (path === "/api/v1/admin/storage-orphans/cleanup") {
        const status = cleanupStatuses.shift() ?? 200;
        if (status !== 200) {
          await route.fulfill({ status, json: { detail: "storage unavailable" } });
          return;
        }
        cleaned = true;
        const body = request.postDataJSON() as { keys?: string[]; uploads?: Array<{ upload_id: string }> };
        await route.fulfill({ json: options.largeOrphanScan
          ? {
              removed: body.keys ?? [],
              aborted_uploads: body.uploads?.map((upload) => upload.upload_id) ?? [],
              skipped: [],
            }
          : {
              removed: ["aura/stray-1"],
              aborted_uploads: ["upload-1"],
              skipped: [{ key: "aura/stray-2", reason: "now accounted for" }],
            } });
        return;
      }
      if (path === "/api/v1/admin/reconcile-terminal") {
        await route.fulfill({
          status: options.terminalStatus ?? 200,
          json: options.terminalStatus
            ? { detail: "storage unavailable" }
            : { cleaned: 2, storage_deletes_attempted: 2, storage_failures: 0 },
        });
        return;
      }
      if (path === "/api/v1/admin/reconcile-reverse") {
        const status = options.reverseStatus ?? 200;
        if (status !== 200) {
          await route.fulfill({ status, json: { detail: "storage unavailable" } });
          return;
        }
        const dryRun = url.searchParams.get("dry_run") === "true";
        await route.fulfill({ json: {
          scanned: 20,
          orphans: 1,
          orphan_keys: [{ bucket: BUCKET, key: "aura/stray", size: 512 }],
          deleted: dryRun ? 0 : 1,
          failures: 0,
          dry_run: dryRun,
        } });
        return;
      }
    }

    await route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
  return { calls, scanCalls };
}

async function loginToAdmin(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}

function section(page: Page, heading: string) {
  return page.locator("section", { has: page.getByRole("heading", { name: heading }) });
}

test("scrub and reverify require confirmation and show success plus mismatch diagnostics", async ({ page }) => {
  const { calls } = await installMocks(page, { reverifyStatuses: [409, 200, 502] });
  await loginToAdmin(page);
  const integrity = section(page, "Intégrité des fichiers");

  await integrity.getByRole("button", { name: "Lancer une vérification d'intégrité" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Annuler" }).click();
  expect(calls).toHaveLength(0);
  await integrity.getByRole("button", { name: "Lancer une vérification d'intégrité" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Vérifier", exact: true }).click();
  await expect(page.getByTestId("scrub-result")).toContainText("2 intact(s), 1 altéré(s)");
  await expect(page.getByTestId("scrub-result")).toContainText("4.0 Ko relu(s)");
  expect(calls[0]).toMatchObject({ path: "/api/v1/admin/integrity/scrub", method: "POST", csrf: CSRF });

  await integrity.getByRole("button", { name: "Re-vérifier contrat.pdf" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Annuler" }).click();
  expect(calls).toHaveLength(1);
  await integrity.getByRole("button", { name: "Re-vérifier contrat.pdf" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Re-vérifier", exact: true }).click();
  await expect(page.getByTestId(`reverify-result-${OBJECT_ID}`)).toContainText("toujours divergent");
  await expect(page.getByTestId(`reverify-result-${OBJECT_ID}`)).toContainText("b".repeat(64));

  await integrity.getByRole("button", { name: "Re-vérifier contrat.pdf" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Re-vérifier", exact: true }).click();
  await expect(page.getByTestId(`reverify-result-${OBJECT_ID}`)).toContainText("de nouveau disponible");
  expect(calls.filter((call) => call.path.endsWith("/reverify"))).toHaveLength(2);
  expect(calls.every((call) => call.csrf === CSRF)).toBe(true);

  await integrity.getByRole("button", { name: "Re-vérifier contrat.pdf" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Re-vérifier", exact: true }).click();
  await expect(page.getByTestId(`reverify-result-${OBJECT_ID}`)).toHaveCount(0);
  await expect(page.getByRole("alert").filter({ hasText: "Re-vérification impossible" }))
    .toContainText("Le stockage ne répond pas");
});

test("orphan cleanup is scanned on demand, confirmed, bounded and reported per item", async ({ page }) => {
  const { calls } = await installMocks(page);
  await loginToAdmin(page);
  const orphans = section(page, "Octets non référencés");

  await expect(orphans.getByTestId("storage-orphans")).toHaveCount(0);
  await orphans.getByRole("button", { name: "Analyser le stockage" }).click();
  await expect(orphans.getByTestId("storage-orphans")).toContainText("2 fichier(s) non référencé(s)");
  expect(calls).toHaveLength(0);

  await orphans.getByRole("button", { name: `Nettoyer les orphelins de ${BUCKET}` }).click();
  const dialog = page.getByRole("dialog", { name: `Nettoyer les orphelins de ${BUCKET}` });
  await expect(dialog).toContainText("Supprimer définitivement 2 fichier(s)");
  await expect(dialog).toContainText("abandonner 1 envoi(s) multipart");
  await dialog.getByRole("button", { name: "Annuler" }).click();
  expect(calls).toHaveLength(0);

  await orphans.getByRole("button", { name: `Nettoyer les orphelins de ${BUCKET}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Nettoyer", exact: true }).click();
  const result = page.getByTestId(`orphan-cleanup-result-${BUCKET}`);
  await expect(result).toContainText("1 fichier(s) supprimé(s), 1 envoi(s) abandonné(s), 1 ignoré(s)");
  await result.getByText("Éléments ignorés et motifs").click();
  await expect(result).toContainText("élément désormais référencé au catalogue");
  expect(calls).toHaveLength(1);
  expect(calls[0]).toMatchObject({
    path: "/api/v1/admin/storage-orphans/cleanup",
    method: "POST",
    csrf: CSRF,
    body: {
      bucket: BUCKET,
      keys: ["aura/stray-1", "aura/stray-2"],
      uploads: [{ key: "aura/partial", upload_id: "upload-1" }],
    },
  });
});

test("orphan scan resumes from next_start_after, retries failures and accumulates pages", async ({ page }) => {
  const { calls, scanCalls } = await installMocks(page, { nextScanStatuses: [502, 200] });
  await loginToAdmin(page);
  const orphans = section(page, "Octets non référencés");

  await orphans.getByRole("button", { name: "Analyser le stockage" }).click();
  await expect(orphans.getByTestId("storage-orphans")).toContainText("analyse partielle");
  const loadMore = orphans.getByRole("button", { name: `Charger la suite du scan de ${BUCKET}` });
  await loadMore.click();
  await expect(page.getByRole("alert").filter({ hasText: "Chargement de la suite du scan impossible" }))
    .toContainText("Le stockage ne répond pas");
  await expect(loadMore).toBeVisible();

  await loadMore.click();
  await expect(orphans.getByTestId("storage-orphans")).toContainText("3 fichier(s) non référencé(s)");
  await expect(orphans.getByTestId("storage-orphans")).toContainText("1 envoi(s) en parties abandonné(s) sur 121");
  await expect(loadMore).toHaveCount(0);
  expect(calls).toHaveLength(0);
  expect(scanCalls).toHaveLength(3);
  const resumed = new URL(scanCalls[1]!);
  expect(resumed.searchParams.get("bucket")).toBe(BUCKET);
  expect(resumed.searchParams.get("start_after")).toBe("aura/stray-2");
  expect(resumed.searchParams.get("max_keys")).toBe("5000");
});

test("a failed cleanup retry clears the previous success and can reset exclusions", async ({ page }) => {
  const { calls } = await installMocks(page, {
    cleanupStatuses: [200, 502],
    keepOrphansAfterCleanup: true,
  });
  await loginToAdmin(page);
  const orphans = section(page, "Octets non référencés");
  await orphans.getByRole("button", { name: "Analyser le stockage" }).click();
  await orphans.getByRole("button", { name: `Nettoyer les orphelins de ${BUCKET}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Nettoyer", exact: true }).click();
  await expect(page.getByTestId(`orphan-cleanup-result-${BUCKET}`)).toBeVisible();

  await orphans.getByRole("button", { name: `Réinitialiser les exclusions de ${BUCKET}` }).click();
  await orphans.getByRole("button", { name: `Nettoyer les orphelins de ${BUCKET}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Nettoyer", exact: true }).click();
  await expect(page.getByTestId(`orphan-cleanup-result-${BUCKET}`)).toHaveCount(0);
  await expect(page.getByRole("alert").filter({ hasText: "Nettoyage des orphelins impossible" }))
    .toContainText("Le stockage ne répond pas");
  expect(calls).toHaveLength(2);
});

test("a persistently failing first cleanup batch does not block the 101st candidate", async ({ page }) => {
  const { calls } = await installMocks(page, {
    largeOrphanScan: true,
    cleanupStatuses: [502, 200],
  });
  await loginToAdmin(page);
  const orphans = section(page, "Octets non référencés");
  await orphans.getByRole("button", { name: "Analyser le stockage" }).click();

  await orphans.getByRole("button", { name: `Nettoyer les orphelins de ${BUCKET}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Nettoyer", exact: true }).click();
  await expect(orphans).toContainText("100 fichier(s) et 0 envoi(s) déjà tentés sont exclus");

  await orphans.getByRole("button", { name: `Nettoyer les orphelins de ${BUCKET}` }).click();
  const dialog = page.getByRole("dialog", { name: `Nettoyer les orphelins de ${BUCKET}` });
  await expect(dialog).toContainText("Supprimer définitivement 1 fichier(s)");
  await dialog.getByRole("button", { name: "Nettoyer", exact: true }).click();
  await expect(page.getByTestId(`orphan-cleanup-result-${BUCKET}`)).toContainText("1 fichier(s) supprimé(s)");
  expect((calls[0]?.body as { keys: string[] }).keys).toHaveLength(100);
  expect((calls[1]?.body as { keys: string[] }).keys).toEqual(["aura/stray-100"]);
});

test("scrub, reverse and cleanup failures are shown as actionable French errors", async ({ page }) => {
  await installMocks(page, { scrubStatus: 502, reverseStatus: 502, cleanupStatuses: [502] });
  await loginToAdmin(page);
  const integrity = section(page, "Intégrité des fichiers");
  await integrity.getByRole("button", { name: "Lancer une vérification d'intégrité" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Vérifier", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Vérification d'intégrité impossible" }))
    .toContainText("Le stockage ne répond pas");

  const maintenance = section(page, "Maintenance et récupération");
  await maintenance.getByRole("button", { name: "Analyser la réconciliation inverse" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Simuler", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Réconciliation inverse impossible" }))
    .toContainText("Le stockage ne répond pas");

  const orphans = section(page, "Octets non référencés");
  await orphans.getByRole("button", { name: "Analyser le stockage" }).click();
  await orphans.getByRole("button", { name: `Nettoyer les orphelins de ${BUCKET}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Nettoyer", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Nettoyage des orphelins impossible" }))
    .toContainText("Le stockage ne répond pas");
});

test("terminal and reverse reconciliation expose dry-run and destructive results", async ({ page }) => {
  const { calls } = await installMocks(page);
  await loginToAdmin(page);
  const maintenance = section(page, "Maintenance et récupération");

  await maintenance.getByRole("button", { name: "Nettoyer les objets terminés" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Annuler" }).click();
  expect(calls).toHaveLength(0);
  await maintenance.getByRole("button", { name: "Nettoyer les objets terminés" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Nettoyer", exact: true }).click();
  await expect(page.getByTestId("terminal-reconcile-result")).toContainText("2 fiche(s) nettoyée(s)");
  expect(calls[0]?.path).toBe("/api/v1/admin/reconcile-terminal?limit=500");

  await maintenance.getByRole("button", { name: "Analyser la réconciliation inverse" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Annuler" }).click();
  expect(calls).toHaveLength(1);
  await maintenance.getByRole("button", { name: "Analyser la réconciliation inverse" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Simuler", exact: true }).click();
  const reverseResult = page.getByTestId("reverse-reconcile-result");
  await expect(reverseResult).toContainText("Simulation terminée");
  await expect(reverseResult).toContainText("0 supprimée(s)");
  await reverseResult.getByText("Clés orphelines retournées (50 maximum)").click();
  await expect(reverseResult).toContainText(`${BUCKET}/aura/stray`);
  expect(calls[1]?.path).toBe("/api/v1/admin/reconcile-reverse?dry_run=true");

  await maintenance.getByRole("button", { name: "Supprimer les orphelins détectés" }).click();
  const destructive = page.getByRole("dialog", { name: "Supprimer les orphelins du stockage" });
  await expect(destructive).toContainText("irréversible");
  await destructive.getByRole("button", { name: "Supprimer", exact: true }).click();
  await expect(reverseResult).toContainText("Suppression terminée");
  await expect(reverseResult).toContainText("1 supprimée(s)");
  expect(calls[2]?.path).toBe("/api/v1/admin/reconcile-reverse?dry_run=false");
  expect(calls.every((call) => call.csrf === CSRF)).toBe(true);
});

test("admin:read alone sees reports but no maintenance command", async ({ page }) => {
  const { calls } = await installMocks(page, { canWrite: false });
  await loginToAdmin(page);

  await expect(page.getByRole("button", { name: "Lancer une vérification d'intégrité" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Re-vérifier contrat.pdf" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Nettoyer les objets terminés" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Analyser la réconciliation inverse" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Supprimer les orphelins détectés" })).toHaveCount(0);
  await expect(section(page, "Maintenance et récupération")).toContainText("lecture seule pour votre compte");

  await section(page, "Octets non référencés").getByRole("button", { name: "Analyser le stockage" }).click();
  await expect(page.getByRole("button", { name: `Nettoyer les orphelins de ${BUCKET}` })).toHaveCount(0);
  await expect(section(page, "Octets non référencés")).toContainText("Le nettoyage exige le droit admin:write");
  expect(calls).toHaveLength(0);
});

test("maintenance errors are shown as actionable French messages", async ({ page }) => {
  await installMocks(page, { terminalStatus: 502 });
  await loginToAdmin(page);
  const maintenance = section(page, "Maintenance et récupération");
  await maintenance.getByRole("button", { name: "Nettoyer les objets terminés" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Nettoyer", exact: true }).click();

  const error = page.getByRole("alert").filter({ hasText: "Nettoyage des objets terminés impossible" });
  await expect(error).toContainText("Le stockage ne répond pas");
  await expect(page.getByTestId("terminal-reconcile-result")).toHaveCount(0);
});
