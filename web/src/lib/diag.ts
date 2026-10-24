import { ApiError } from "./api";

/**
 * Mesures du chemin réel navigateur → Aura.
 *
 * Ookla mesure le lien vers un serveur qui n'est pas le nôtre ; ces helpers
 * mesurent TLS, Traefik et l'API tels que l'application les traverse. Aucune
 * de ces fonctions ne stocke quoi que ce soit : le serveur ne fait que compter
 * des octets et du temps (plafond 25 Mo par sens, côté API).
 */

export const DIAG_PING_COUNT = 10;
export const DIAG_DOWNLOAD_BYTES = 10_000_000;
export const DIAG_UPLOAD_BYTES = 5_000_000;

export interface PingStats {
  samples: number[];
  min: number;
  avg: number;
  max: number;
  /** Gigue : écart absolu moyen entre deux allers-retours consécutifs. */
  jitter: number;
}

export interface RateSample {
  bytes: number;
  durationMs: number;
  bytesPerSecond: number;
}

export interface UploadSample extends RateSample {
  /** Débit vu par le serveur : l'écart révèle des octets perdus en route. */
  serverBytesPerSecond: number;
}

/** Statistiques d'une série de temps d'aller-retour (ms). */
export function msStats(samples: number[]): PingStats {
  if (samples.length === 0) {
    return { samples: [], min: 0, avg: 0, max: 0, jitter: 0 };
  }
  let sum = 0;
  let min = Infinity;
  let max = 0;
  for (const value of samples) {
    sum += value;
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  let spread = 0;
  for (let i = 1; i < samples.length; i += 1) {
    spread += Math.abs((samples[i] as number) - (samples[i - 1] as number));
  }
  return {
    samples,
    min,
    avg: sum / samples.length,
    max,
    jitter: samples.length > 1 ? spread / (samples.length - 1) : 0,
  };
}

/** Débit en octets/s, jamais négatif ni infini. */
export function rateOf(bytes: number, durationMs: number): number {
  if (bytes <= 0 || durationMs <= 0) return 0;
  return (bytes * 1000) / durationMs;
}

/** "12,4 Mbit/s (1,55 Mo/s)" — virgule décimale française. */
export function formatRatePair(bytesPerSecond: number): string {
  const mbps = (bytesPerSecond * 8) / 1_000_000;
  const mo = bytesPerSecond / 1_000_000;
  return `${mbps.toFixed(1).replace(".", ",")} Mbit/s (${mo
    .toFixed(2)
    .replace(".", ",")} Mo/s)`;
}

export interface Verdict {
  label: string;
  tone: "bad" | "warn" | "ok";
}

/** Lecture du débit montant, calée sur ce qu'un envoi multipart peut tenir. */
export function verdict(bytesPerSecond: number): Verdict {
  const mbps = (bytesPerSecond * 8) / 1_000_000;
  if (mbps < 2) return { label: "Très faible : envois longs, coupures probables", tone: "bad" };
  if (mbps < 8) return { label: "Faible : les gros fichiers resteront lents", tone: "warn" };
  if (mbps < 25) return { label: "Correct : les envois multipart passent", tone: "ok" };
  return { label: "Bon : le chemin ne limite pas les envois", tone: "ok" };
}

async function checked(response: Response): Promise<Response> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string" && data.detail.length > 0) {
        detail = data.detail;
      }
    } catch {
      // Corps non JSON : le statut suffit.
    }
    throw new ApiError(response.status, detail);
  }
  return response;
}

async function pingOnce(): Promise<number> {
  const started = performance.now();
  const response = await checked(
    await fetch("/api/v1/diag/ping", { cache: "no-store", credentials: "include" }),
  );
  await response.json();
  return performance.now() - started;
}

/** Allers-retours séquentiels : la gigue explique mieux les coupures qu'un débit. */
export async function runPing(count = DIAG_PING_COUNT): Promise<PingStats> {
  const samples: number[] = [];
  for (let i = 0; i < Math.max(1, count); i += 1) {
    samples.push(await pingOnce());
  }
  return msStats(samples);
}

/** Descente en flux : on lit par morceaux, jamais `arrayBuffer()` complet. */
export async function runDownload(
  total = DIAG_DOWNLOAD_BYTES,
  onProgress?: (loaded: number, total: number) => void,
): Promise<RateSample> {
  const started = performance.now();
  const response = await checked(
    await fetch(`/api/v1/diag/download?bytes=${Math.max(1, Math.floor(total))}`, {
      cache: "no-store",
      credentials: "include",
    }),
  );
  const reader = response.body?.getReader();
  let bytes = 0;
  if (reader) {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value?.byteLength ?? 0;
      onProgress?.(bytes, total);
    }
  } else {
    // Navigateur sans flux : repli correct mais mémoire proportionnelle au bloc.
    bytes = (await response.arrayBuffer()).byteLength;
    onProgress?.(bytes, total);
  }
  const durationMs = performance.now() - started;
  return { bytes, durationMs, bytesPerSecond: rateOf(bytes, durationMs) };
}

/** Montée : débit navigateur + débit serveur, pour détecter les octets perdus. */
export async function runUpload(
  bytes = DIAG_UPLOAD_BYTES,
  csrf: string | null,
): Promise<UploadSample> {
  const payload = new Uint8Array(Math.max(1, Math.floor(bytes)));
  const started = performance.now();
  const response = await checked(
    await fetch("/api/v1/diag/upload", {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: {
        "content-type": "application/octet-stream",
        ...(csrf ? { "x-csrf-token": csrf } : {}),
      },
      body: payload,
    }),
  );
  const durationMs = performance.now() - started;
  const data = (await response.json()) as {
    bytes?: unknown;
    bytes_per_second?: unknown;
  };
  const serverBytes =
    typeof data.bytes === "number" && Number.isFinite(data.bytes) ? data.bytes : payload.byteLength;
  const serverRate =
    typeof data.bytes_per_second === "number" && Number.isFinite(data.bytes_per_second)
      ? data.bytes_per_second
      : 0;
  return {
    bytes: serverBytes,
    durationMs,
    bytesPerSecond: rateOf(serverBytes, durationMs),
    serverBytesPerSecond: serverRate,
  };
}
