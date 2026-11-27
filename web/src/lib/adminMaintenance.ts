import type {
  OrphanCleanupInput,
  OrphanCleanupResult,
  StorageOrphanBucket,
  StorageOrphanReport,
} from "./api";

/** Backend cap for each list in POST /admin/storage-orphans/cleanup. */
export const ORPHAN_CLEANUP_MAX_ITEMS = 100;

export interface OrphanCleanupBatch {
  input: OrphanCleanupInput;
  remainingKeys: number;
  remainingUploads: number;
  excludedKeys: number;
  excludedUploads: number;
}

export interface OrphanCleanupExclusions {
  keys: ReadonlySet<string>;
  uploads: ReadonlySet<string>;
}

/**
 * Build one explicit cleanup request from a read-only scan.
 *
 * Never infer work from a bucket-wide command: the backend receives only the
 * candidates in this bounded batch and re-checks each one before deleting it.
 */
export function buildOrphanCleanupBatch(
  entry: StorageOrphanBucket,
  exclusions?: OrphanCleanupExclusions,
): OrphanCleanupBatch {
  const allOrphans = entry.error ? [] : (entry.orphans ?? []);
  const allUploads = entry.error ? [] : (entry.stale_uploads ?? []);
  // A failed item at the head must not monopolise every later 100-item batch.
  // Attempted items stay excluded until the operator explicitly resets them.
  const orphans = allOrphans.filter((orphan) => !exclusions?.keys.has(orphan.key));
  const uploads = allUploads.filter((upload) => !exclusions?.uploads.has(upload.upload_id));
  return {
    input: {
      bucket: entry.bucket,
      keys: orphans.slice(0, ORPHAN_CLEANUP_MAX_ITEMS).map((orphan) => orphan.key),
      uploads: uploads.slice(0, ORPHAN_CLEANUP_MAX_ITEMS).map((upload) => ({
        key: upload.key,
        upload_id: upload.upload_id,
      })),
    },
    remainingKeys: Math.max(0, orphans.length - ORPHAN_CLEANUP_MAX_ITEMS),
    remainingUploads: Math.max(0, uploads.length - ORPHAN_CLEANUP_MAX_ITEMS),
    excludedKeys: allOrphans.length - orphans.length,
    excludedUploads: allUploads.length - uploads.length,
  };
}

/** Accumulate one cursor page without duplicating keys or multipart uploads. */
export function mergeStorageOrphanPage(
  report: StorageOrphanReport,
  page: StorageOrphanReport,
): StorageOrphanReport {
  return {
    ...report,
    checked_at: page.checked_at,
    buckets: report.buckets.map((entry) => {
      const next = page.buckets.find((candidate) => candidate.bucket === entry.bucket);
      if (!next) return entry;
      const orphans = [...(entry.orphans ?? [])];
      const seenKeys = new Set(orphans.map((orphan) => orphan.key));
      for (const orphan of next.orphans ?? []) {
        if (seenKeys.has(orphan.key)) continue;
        seenKeys.add(orphan.key);
        orphans.push(orphan);
      }
      const uploads = [...(entry.stale_uploads ?? [])];
      const seenUploads = new Set(uploads.map((upload) => upload.upload_id));
      for (const upload of next.stale_uploads ?? []) {
        if (seenUploads.has(upload.upload_id)) continue;
        seenUploads.add(upload.upload_id);
        uploads.push(upload);
      }
      return {
        ...entry,
        scanned: (entry.scanned ?? 0) + (next.scanned ?? 0),
        orphans,
        orphan_bytes: orphans.reduce((total, orphan) => total + orphan.size_bytes, 0),
        stale_uploads: uploads,
        next_start_after: next.next_start_after ?? null,
      };
    }),
  };
}

/** Remove confirmed deletions from the accumulated scan without losing its cursor. */
export function applyOrphanCleanupResult(
  report: StorageOrphanReport,
  bucket: string,
  result: OrphanCleanupResult,
): StorageOrphanReport {
  const removed = new Set(result.removed);
  const aborted = new Set(result.aborted_uploads);
  return {
    ...report,
    buckets: report.buckets.map((entry) => {
      if (entry.bucket !== bucket) return entry;
      const orphans = (entry.orphans ?? []).filter((orphan) => !removed.has(orphan.key));
      return {
        ...entry,
        orphans,
        orphan_bytes: orphans.reduce((total, orphan) => total + orphan.size_bytes, 0),
        stale_uploads: (entry.stale_uploads ?? []).filter(
          (upload) => !aborted.has(upload.upload_id),
        ),
      };
    }),
  };
}
