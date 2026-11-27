import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import type { StorageOrphanBucket, StorageOrphanReport } from "./api";
import {
  applyOrphanCleanupResult,
  buildOrphanCleanupBatch,
  mergeStorageOrphanPage,
  ORPHAN_CLEANUP_MAX_ITEMS,
} from "./adminMaintenance";

const CSRF = "csrf-maintenance";

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockJson(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function call(fetchMock: ReturnType<typeof vi.fn>): [string, RequestInit] {
  return fetchMock.mock.calls[0] as [string, RequestInit];
}

describe("admin maintenance API methods", () => {
  it("starts one bounded integrity scrub with CSRF", async () => {
    const result = { ok: 3, mismatch: 1, missing: 0, error: 0, bytes: 4096 };
    const fetchMock = mockJson(200, result);

    await expect(api.scrubIntegrity(CSRF)).resolves.toEqual(result);
    const [path, init] = call(fetchMock);
    expect(path).toBe("/api/v1/admin/integrity/scrub");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.headers).toMatchObject({ "x-csrf-token": CSRF });
    expect(init.body).toBeUndefined();
  });

  it("re-verifies an encoded object id", async () => {
    const result = {
      id: "object/with space",
      status: "available",
      size_bytes: 12,
      checksum_sha256: "a".repeat(64),
    };
    const fetchMock = mockJson(200, result);

    await expect(api.reverifyObject(result.id, CSRF)).resolves.toEqual(result);
    const [path, init] = call(fetchMock);
    expect(path).toBe("/api/v1/admin/objects/object%2Fwith%20space/reverify");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "x-csrf-token": CSRF });
  });

  it("keeps the structured diagnostic when reverification still mismatches", async () => {
    const payload = {
      id: "object-1",
      status: "suspect",
      reason: "checksum_mismatch",
      size_bytes: 12,
      checksum_sha256: "b".repeat(64),
    };
    mockJson(409, payload);

    const error = await api.reverifyObject("object-1", CSRF).catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, payload });
  });

  it("passes the terminal reconciliation limit as a query parameter", async () => {
    const result = { cleaned: 2, storage_deletes_attempted: 2, storage_failures: 0 };
    const fetchMock = mockJson(200, result);

    await expect(api.reconcileTerminal(CSRF, 42)).resolves.toEqual(result);
    const [path, init] = call(fetchMock);
    expect(path).toBe("/api/v1/admin/reconcile-terminal?limit=42");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "x-csrf-token": CSRF });
  });

  it.each([true, false])("sets reverse reconciliation dry_run=%s explicitly", async (dryRun) => {
    const result = {
      scanned: 10,
      orphans: 1,
      orphan_keys: [{ bucket: "aura", key: "aura/stray", size: 5 }],
      deleted: dryRun ? 0 : 1,
      failures: 0,
      dry_run: dryRun,
    };
    const fetchMock = mockJson(200, result);

    await expect(api.reconcileReverse(CSRF, dryRun)).resolves.toEqual(result);
    const [path] = call(fetchMock);
    expect(path).toBe(`/api/v1/admin/reconcile-reverse?dry_run=${String(dryRun)}`);
  });

  it("resumes a storage orphan scan with an encoded bucket cursor", async () => {
    const report = { grace_seconds: 86400, buckets: [], checked_at: 1_700_000_000 };
    const fetchMock = mockJson(200, report);

    await expect(api.adminStorageOrphans({
      bucket: "aura test",
      startAfter: "aura/page/one",
      maxKeys: 5000,
    })).resolves.toEqual(report);
    const [path, init] = call(fetchMock);
    expect(path).toBe(
      "/api/v1/admin/storage-orphans?bucket=aura+test&start_after=aura%2Fpage%2Fone&max_keys=5000",
    );
    expect(init.method).toBe("GET");
  });

  it("keeps the initial storage orphan scan unbucketed and uncursored", async () => {
    const report = { grace_seconds: 86400, buckets: [], checked_at: 1_700_000_000 };
    const fetchMock = mockJson(200, report);

    await api.adminStorageOrphans();
    expect(call(fetchMock)[0]).toBe("/api/v1/admin/storage-orphans");
  });

  it("sends only the selected orphan keys and uploads for one bucket", async () => {
    const input = {
      bucket: "aura",
      keys: ["aura/stray"],
      uploads: [{ key: "aura/partial", upload_id: "upload-1" }],
    };
    const result = { removed: ["aura/stray"], aborted_uploads: ["upload-1"], skipped: [] };
    const fetchMock = mockJson(200, result);

    await expect(api.cleanupStorageOrphans(input, CSRF)).resolves.toEqual(result);
    const [path, init] = call(fetchMock);
    expect(path).toBe("/api/v1/admin/storage-orphans/cleanup");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "content-type": "application/json",
      "x-csrf-token": CSRF,
    });
    expect(JSON.parse(String(init.body))).toEqual(input);
  });
});

describe("bounded orphan cleanup batches", () => {
  it("pins the backend cleanup bound explicitly at 100 items per list", () => {
    expect(ORPHAN_CLEANUP_MAX_ITEMS).toBe(100);
  });

  it("never sends more than 100 keys or 100 uploads and reports the remainder", () => {
    const entry: StorageOrphanBucket = {
      bucket: "aura",
      orphans: Array.from({ length: 101 }, (_, index) => ({
        key: `aura/stray-${index}`,
        size_bytes: 1,
        last_modified: 1,
        reason: "no_row",
        object_id: null,
      })),
      stale_uploads: Array.from({ length: 102 }, (_, index) => ({
        key: `aura/partial-${index}`,
        upload_id: `upload-${index}`,
        initiated: 1,
      })),
    };

    const batch = buildOrphanCleanupBatch(entry);
    expect(batch.input.bucket).toBe("aura");
    expect(batch.input.keys).toHaveLength(ORPHAN_CLEANUP_MAX_ITEMS);
    expect(batch.input.uploads).toHaveLength(ORPHAN_CLEANUP_MAX_ITEMS);
    expect(batch.remainingKeys).toBe(1);
    expect(batch.remainingUploads).toBe(2);
  });

  it("excludes an already attempted failing head so later candidates can proceed", () => {
    const entry: StorageOrphanBucket = {
      bucket: "aura",
      orphans: Array.from({ length: 101 }, (_, index) => ({
        key: `aura/stray-${index}`,
        size_bytes: 1,
        last_modified: 1,
        reason: "no_row",
        object_id: null,
      })),
    };
    const attemptedKeys = new Set(entry.orphans!.slice(0, 100).map((orphan) => orphan.key));
    const batch = buildOrphanCleanupBatch(entry, { keys: attemptedKeys, uploads: new Set() });

    expect(batch.input.keys).toEqual(["aura/stray-100"]);
    expect(batch.remainingKeys).toBe(0);
    expect(batch.excludedKeys).toBe(100);
  });

  it("does not infer cleanup work from a failed or empty scan", () => {
    expect(buildOrphanCleanupBatch({ bucket: "aura", error: "storage unavailable" }).input)
      .toEqual({ bucket: "aura", keys: [], uploads: [] });
    expect(buildOrphanCleanupBatch({ bucket: "aura" }).input)
      .toEqual({ bucket: "aura", keys: [], uploads: [] });
  });
});

describe("storage orphan cursor pages", () => {
  const first: StorageOrphanReport = {
    grace_seconds: 86400,
    checked_at: 1,
    buckets: [{
      bucket: "aura",
      scanned: 2,
      orphan_bytes: 5,
      orphans: [{ key: "aura/one", size_bytes: 5, last_modified: 1, reason: "no_row", object_id: null }],
      stale_uploads: [{ key: "aura/partial", upload_id: "upload-1", initiated: 1 }],
      next_start_after: "aura/one",
    }],
  };

  it("accumulates the next cursor page and deduplicates repeated multipart uploads", () => {
    const next: StorageOrphanReport = {
      grace_seconds: 86400,
      checked_at: 2,
      buckets: [{
        bucket: "aura",
        scanned: 1,
        orphan_bytes: 3,
        orphans: [{ key: "aura/two", size_bytes: 3, last_modified: 1, reason: "no_row", object_id: null }],
        stale_uploads: [{ key: "aura/partial", upload_id: "upload-1", initiated: 1 }],
        next_start_after: null,
      }],
    };

    const merged = mergeStorageOrphanPage(first, next);
    expect(merged.checked_at).toBe(2);
    expect(merged.buckets[0]?.scanned).toBe(3);
    expect(merged.buckets[0]?.orphans?.map((orphan) => orphan.key)).toEqual(["aura/one", "aura/two"]);
    expect(merged.buckets[0]?.orphan_bytes).toBe(8);
    expect(merged.buckets[0]?.stale_uploads).toHaveLength(1);
    expect(merged.buckets[0]?.next_start_after).toBeNull();
  });

  it("removes confirmed cleanup results without discarding accumulated pages or the cursor", () => {
    const accumulated = mergeStorageOrphanPage(first, {
      grace_seconds: 86400,
      checked_at: 2,
      buckets: [{
        bucket: "aura",
        scanned: 1,
        orphans: [{ key: "aura/two", size_bytes: 3, last_modified: 1, reason: "no_row", object_id: null }],
        next_start_after: "aura/two",
      }],
    });
    const cleaned = applyOrphanCleanupResult(accumulated, "aura", {
      removed: ["aura/one"],
      aborted_uploads: ["upload-1"],
      skipped: [],
    });

    expect(cleaned.buckets[0]?.orphans?.map((orphan) => orphan.key)).toEqual(["aura/two"]);
    expect(cleaned.buckets[0]?.orphan_bytes).toBe(3);
    expect(cleaned.buckets[0]?.stale_uploads).toEqual([]);
    expect(cleaned.buckets[0]?.next_start_after).toBe("aura/two");
  });
});
