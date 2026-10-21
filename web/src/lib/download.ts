// Resumable download helper for AURA.
//
// SeaweedFS (and any S3-compatible backend) honours Range requests on a
// presigned GET, so a large or flaky download can be fetched in chunks and
// resumed after a network error instead of restarting from byte 0.
//
// The helper collects chunks in memory and returns a Blob; callers that need
// to persist to disk should use the File System Access API on top of it.
// Integrity is verified against the stored SHA-256 when `expectedSha256` is
// provided (Web Crypto, no dependency).

export interface DownloadOptions {
  url: string;
  expectedSize?: number;
  expectedSha256?: string;
  chunkBytes?: number;
  signal?: AbortSignal;
  onProgress?: (loaded: number, total: number) => void;
}

export interface DownloadResult {
  blob: Blob;
  sha256: string;
  integrityOk: boolean;
}

export async function downloadResumable(opts: DownloadOptions): Promise<DownloadResult> {
  const chunkBytes = opts.chunkBytes ?? 8 * 1024 * 1024;
  const total = opts.expectedSize ?? await probeSize(opts.url, opts.signal);
  const chunks: Uint8Array[] = [];
  let loaded = 0;

  while (loaded < total) {
    const end = Math.min(loaded + chunkBytes - 1, total - 1);
    const res = await fetch(opts.url, {
      headers: { Range: `bytes=${loaded}-${end}` },
      signal: opts.signal,
    });
    if (!res.ok && res.status !== 206) {
      throw new Error(`download failed: ${res.status}`);
    }
    const buf = new Uint8Array(await res.arrayBuffer());
    if (buf.length === 0) break;
    chunks.push(buf);
    loaded += buf.length;
    opts.onProgress?.(loaded, total);
  }

  const out = new Uint8Array(loaded);
  let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.length; }
  const blob = new Blob([out]);
  const sha256 = await sha256Hex(out);
  const integrityOk = !opts.expectedSha256 || sha256 === opts.expectedSha256.toLowerCase();
  return { blob, sha256, integrityOk };
}

async function probeSize(url: string, signal?: AbortSignal): Promise<number> {
  const res = await fetch(url, { method: "HEAD", signal });
  const len = res.headers.get("content-length");
  if (!len) throw new Error("missing content-length");
  return Number(len);
}

async function sha256Hex(data: Uint8Array): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
