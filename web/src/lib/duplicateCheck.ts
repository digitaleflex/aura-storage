export interface ExistingObjectRef {
  id: string;
  display_name: string;
  size_bytes: number;
  checksum_sha256?: string | null;
}

export type DuplicateReason =
  | "name_size"
  | "checksum"
  | "batch_name_size"
  | "batch_checksum";

export interface DuplicateMatch {
  key: string;
  file: File;
  rel: string;
  reason: DuplicateReason;
  existing?: ExistingObjectRef;
  duplicateOf?: string;
}

export type PreflightStatus = "queued" | "checking" | "ready" | "duplicate" | "error";

export interface PreflightResult {
  status: PreflightStatus;
  match?: DuplicateMatch;
}

export interface DuplicateEntry {
  key: string;
  file: File;
  rel: string;
}

export interface DuplicateScanOptions {
  computeHash?: boolean;
  hashMaxBytes?: number;
  /** Hash every small file so renamed duplicates can be found too. */
  hashAllUnderBytes?: number;
  signal?: AbortSignal;
  onResult?: (entry: DuplicateEntry, result: PreflightResult) => void;
}

export interface DuplicateScanReport {
  matches: DuplicateMatch[];
  results: Map<string, PreflightResult>;
}

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function partsOf(rel: string): { parent: string; name: string } {
  const normalized = rel.replace(/\\/g, "/");
  const slash = normalized.lastIndexOf("/");
  return {
    parent: slash >= 0 ? normalized.slice(0, slash) : "",
    name: slash >= 0 ? normalized.slice(slash + 1) : normalized,
  };
}

function nameSizeKey(parent: string, name: string, size: number): string {
  return `${parent}\u0000${name}\u0000${size}`;
}

/**
 * Scan one import batch progressively.
 *
 * Large files are hashed only when name + size already make them plausible
 * duplicates. Small files are hashed as well, which catches identical content
 * saved under a different name. Every result is emitted as soon as it is known
 * so the UI can show verification and duplicates while the batch is scanned.
 */
export async function scanDuplicates(
  files: DuplicateEntry[],
  existingByKey: Map<string, ExistingObjectRef[]>,
  opts: DuplicateScanOptions = {},
): Promise<DuplicateScanReport> {
  const computeHash = opts.computeHash ?? true;
  const hashMaxBytes = opts.hashMaxBytes ?? 256 * 1024 * 1024;
  const hashAllUnderBytes = opts.hashAllUnderBytes ?? 8 * 1024 * 1024;
  const matches: DuplicateMatch[] = [];
  const results = new Map<string, PreflightResult>();

  const existingChecksums = new Map<string, Map<string, ExistingObjectRef>>();
  for (const [parent, objects] of existingByKey) {
    const byChecksum = new Map<string, ExistingObjectRef>();
    for (const object of objects) {
      const checksum = (object.checksum_sha256 || "").toLowerCase();
      if (checksum && !byChecksum.has(checksum)) byChecksum.set(checksum, object);
    }
    existingChecksums.set(parent, byChecksum);
  }

  const batchByNameSize = new Map<string, DuplicateEntry[]>();
  const batchByChecksum = new Map<string, Map<string, DuplicateEntry[]>>();
  const batchChecksumByKey = new Map<string, string | null>();

  for (const entry of files) {
    if (opts.signal?.aborted) throw new DOMException("Scan annulé", "AbortError");
    const checking: PreflightResult = { status: "checking" };
    results.set(entry.key, checking);
    opts.onResult?.(entry, checking);

    const { parent, name } = partsOf(entry.rel);
    const key = nameSizeKey(parent, name, entry.file.size);
    const sameNameSize = (existingByKey.get(parent) ?? []).filter(
      (object) => object.display_name === name && object.size_bytes === entry.file.size,
    );
    const sameBatchNameSize = batchByNameSize.get(key) ?? [];
    const existingByChecksum = existingChecksums.get(parent);
    const batchChecksums: Map<string, DuplicateEntry[]> | undefined = batchByChecksum.get(parent);
    const smallEnoughToHash = computeHash && entry.file.size <= hashAllUnderBytes;
    const plausibleHashCandidate =
      computeHash &&
      entry.file.size <= hashMaxBytes &&
      (sameNameSize.some((object) => object.checksum_sha256) ||
        sameBatchNameSize.length > 0 ||
        (existingByChecksum?.size ?? 0) > 0 ||
        (batchChecksums?.size ?? 0) > 0);

    let checksum: string | null = null;
    let hashFailed = false;
    if (smallEnoughToHash || plausibleHashCandidate) {
      try {
        checksum = await sha256Hex(entry.file);
      } catch {
        hashFailed = true;
      }
    }
    if (opts.signal?.aborted) throw new DOMException("Scan annulé", "AbortError");
    if (hashFailed) {
      const result: PreflightResult = { status: "error" };
      results.set(entry.key, result);
      opts.onResult?.(entry, result);
      batchChecksumByKey.set(key, null);
      continue;
    }

    let match: DuplicateMatch | undefined;
    if (checksum) {
      const existing = existingByChecksum?.get(checksum);
      const previousEntries: DuplicateEntry[] | undefined = batchChecksums?.get(checksum);
      const previous = previousEntries?.[0];
      if (existing) {
        match = { key: entry.key, file: entry.file, rel: entry.rel, reason: "checksum", existing };
      } else if (previous) {
        match = {
          key: entry.key,
          file: entry.file,
          rel: entry.rel,
          reason: "batch_checksum",
          duplicateOf: previous.rel,
        };
      }
    }
    const existingHasUnverifiableChecksum = sameNameSize.some((object) => !object.checksum_sha256);
    if (!match && sameNameSize[0] && (!checksum || existingHasUnverifiableChecksum)) {
      match = {
        key: entry.key,
        file: entry.file,
        rel: entry.rel,
        reason: "name_size",
        existing: sameNameSize[0],
      };
    }
    const previousBatchChecksum = batchChecksumByKey.get(key);
    if (!match && sameBatchNameSize[0] && (!checksum || !previousBatchChecksum)) {
      match = {
        key: entry.key,
        file: entry.file,
        rel: entry.rel,
        reason: "batch_name_size",
        duplicateOf: sameBatchNameSize[0].rel,
      };
    }

    const result: PreflightResult = match
      ? { status: "duplicate", match }
      : { status: "ready" };
    results.set(entry.key, result);
    if (match) matches.push(match);
    opts.onResult?.(entry, result);

    const named = batchByNameSize.get(key) ?? [];
    named.push(entry);
    batchByNameSize.set(key, named);
    if (checksum) {
      const byChecksum: Map<string, DuplicateEntry[]> =
        batchByChecksum.get(parent) ?? new Map<string, DuplicateEntry[]>();
      const sameChecksum: DuplicateEntry[] = byChecksum.get(checksum) ?? [];
      sameChecksum.push(entry);
      byChecksum.set(checksum, sameChecksum);
      batchByChecksum.set(parent, byChecksum);
      batchChecksumByKey.set(key, checksum);
    } else {
      batchChecksumByKey.set(key, null);
    }
  }

  return { matches, results };
}

/** Backward-compatible helper for callers that only need the match list. */
export async function findDuplicates(
  files: DuplicateEntry[],
  existingByKey: Map<string, ExistingObjectRef[]>,
  opts: DuplicateScanOptions = {},
): Promise<DuplicateMatch[]> {
  const report = await scanDuplicates(files, existingByKey, opts);
  return report.matches;
}
