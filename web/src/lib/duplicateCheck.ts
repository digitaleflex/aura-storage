export interface ExistingObjectRef {
  id: string;
  display_name: string;
  size_bytes: number;
  checksum_sha256?: string | null;
}

export interface DuplicateMatch {
  file: File;
  rel: string;
  reason: "name_size" | "checksum";
  existing: ExistingObjectRef;
}

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function findDuplicates(
  files: { file: File; rel: string }[],
  existingByKey: Map<string, ExistingObjectRef[]>,
  opts?: { computeHash?: boolean; hashMaxBytes?: number },
): Promise<DuplicateMatch[]> {
  const computeHash = opts?.computeHash ?? true;
  const hashMaxBytes = opts?.hashMaxBytes ?? 256 * 1024 * 1024;
  const matches: DuplicateMatch[] = [];

  for (const entry of files) {
    const baseName = entry.rel.split("/").pop() ?? entry.rel;
    const parentKey = entry.rel.includes("/")
      ? entry.rel.slice(0, entry.rel.lastIndexOf("/"))
      : "";
    const existing = existingByKey.get(parentKey) ?? [];
    const sameName = existing.filter((o) => o.display_name === baseName);
    const sameNameSize = sameName.filter((o) => o.size_bytes === entry.file.size);

    if (sameNameSize.length > 0) {
      // Strong check when checksum is available.
      let checksum: string | null = null;
      const needsHash =
        computeHash && entry.file.size <= hashMaxBytes && sameNameSize.some((o) => o.checksum_sha256);
      if (needsHash) {
        try {
          checksum = await sha256Hex(entry.file);
        } catch {
          checksum = null;
        }
      }
      const checksumMatch = checksum
        ? sameNameSize.find((o) => (o.checksum_sha256 || "").toLowerCase() === checksum)
        : undefined;
      if (checksumMatch) {
        matches.push({ file: entry.file, rel: entry.rel, reason: "checksum", existing: checksumMatch });
      } else {
        matches.push({ file: entry.file, rel: entry.rel, reason: "name_size", existing: sameNameSize[0]! });
      }
    }
  }
  return matches;
}
