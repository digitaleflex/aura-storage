import { test, expect } from "@playwright/test";
import {
  formatRatePair,
  msStats,
  rateOf,
  runDownload,
  runUpload,
  verdict,
} from "../src/lib/diag";

/**
 * Le diagnostic réseau doit être juste : ses chiffres servent à décider si le
 * problème vient du lien, du transit ou de la chaîne Aura. On teste donc les
 * agrégats (RTT, gigue), la lecture en flux et la remontée du débit serveur,
 * sans navigateur ni réseau réel.
 */

test("msStats agrège minimum, moyenne, maximum et gigue", () => {
  const stats = msStats([100, 120, 110]);
  expect(stats.min).toBe(100);
  expect(stats.max).toBe(120);
  expect(stats.avg).toBeCloseTo(110, 5);
  // |120-100| + |110-120| = 30, sur 2 intervalles.
  expect(stats.jitter).toBeCloseTo(15, 5);
  expect(msStats([]).avg).toBe(0);
});

test("rateOf ne rend jamais de débit absurde", () => {
  expect(rateOf(1000, 1000)).toBe(1000);
  expect(rateOf(0, 1000)).toBe(0);
  expect(rateOf(1000, 0)).toBe(0);
});

test("verdict classe le débit montant en Mbit/s", () => {
  expect(verdict(100_000).tone).toBe("bad"); // 0,8 Mbit/s
  expect(verdict(500_000).tone).toBe("warn"); // 4 Mbit/s
  expect(verdict(1_500_000).tone).toBe("ok"); // 12 Mbit/s
  expect(verdict(5_000_000).label).toContain("Bon");
});

test("les débits s'écrivent à la française", () => {
  const text = formatRatePair(1_250_000);
  expect(text).toContain("Mbit/s");
  expect(text).toContain(",");
  expect(text).not.toContain(".");
});

function streamResponse(bytes: Uint8Array): Response {
  let offset = 0;
  const reader = {
    read: async () => {
      if (offset >= bytes.byteLength) return { done: true as const, value: undefined };
      const slice = bytes.slice(offset, Math.min(offset + 1000, bytes.byteLength));
      offset += slice.byteLength;
      return { done: false as const, value: slice };
    },
  };
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    body: { getReader: () => reader },
    json: async () => ({}),
  } as unknown as Response;
}

test("la descente lit le flux morceau par morceau", async () => {
  const original = globalThis.fetch;
  const payload = new Uint8Array(2500).fill(7);
  globalThis.fetch = (async () => streamResponse(payload)) as typeof fetch;
  try {
    const progress: number[] = [];
    const sample = await runDownload(2500, (loaded) => progress.push(loaded));
    expect(sample.bytes).toBe(2500);
    expect(progress.at(-1)).toBe(2500);
    expect(sample.durationMs).toBeGreaterThanOrEqual(0);
  } finally {
    globalThis.fetch = original;
  }
});

test("la montée remonte le débit mesuré par le serveur", async () => {
  const original = globalThis.fetch;
  let body: unknown = null;
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    body = init?.body;
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      body: null,
      json: async () => ({ bytes: 3000, duration_ms: 30, bytes_per_second: 100_000 }),
    } as unknown as Response;
  }) as typeof fetch;
  try {
    const sample = await runUpload(3000, "csrf-test");
    expect(body).toBeInstanceOf(Uint8Array);
    expect((body as Uint8Array).byteLength).toBe(3000);
    expect(sample.bytes).toBe(3000);
    expect(sample.serverBytesPerSecond).toBe(100_000);
    expect(sample.bytesPerSecond).toBeGreaterThan(0);
  } finally {
    globalThis.fetch = original;
  }
});
