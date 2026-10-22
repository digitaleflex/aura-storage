import { test, expect } from "@playwright/test";
import { PresignedUploadError } from "../src/lib/api";
import { runTransfer, startUploadQueue } from "../src/lib/transfer";
import type { TransferDeps } from "../src/lib/transfer";

/**
 * A PUT that runs for a long time and then dies (the proxy's readTimeout) is not
 * a blip: resending from zero at the same pace dies at the same place. The engine
 * gives the file the whole uplink, and stops after a second identical failure.
 */

const file = (name: string) => ({ name, size: 10, type: "video/mp4" }) as unknown as File;

function deps(upload: TransferDeps["upload"]): TransferDeps {
  return {
    requestIntent: async (input) => ({
      id: input.fileName, status: "pending", method: "PUT", upload_url: "https://s3.example/put",
      headers: {}, content_type: "video/mp4", size_bytes: input.sizeBytes, expires_in: 900,
      expires_at: null, idempotent_replay: false,
    }),
    upload,
    commit: async (id) => ({ id, status: "available", size_bytes: 10, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };
}

const cut = () => new PresignedUploadError("network", 0, "network error");

test("a short failure is an ordinary retry: no cut is declared", async () => {
  let clock = 0;
  let calls = 0;
  let cuts = 0;
  const result = await runTransfer(file("a.mp4"), deps(async () => {
    calls += 1;
    clock += 5_000;
    if (calls === 1) throw cut();
  }), { folderId: null, idempotencyKey: "k", now: () => clock, onLongPutCut: () => { cuts += 1; } });
  expect(result.state.phase).toBe("available");
  expect(cuts).toBe(0);
  expect(result.state.longPutCuts).toBeUndefined();
});

test("a PUT cut after a long run asks the queue for the whole uplink, then retries", async () => {
  let clock = 0;
  let calls = 0;
  let cuts = 0;
  const seen: Array<string | null> = [];
  const result = await runTransfer(file("big.mp4"), deps(async () => {
    calls += 1;
    if (calls === 1) {
      clock += 1_200_000; // 20 minutes, then the connection is cut
      throw cut();
    }
    clock += 60_000;
  }), {
    folderId: null, idempotencyKey: "k", now: () => clock,
    onLongPutCut: () => { cuts += 1; },
    onUpdate: (s) => seen.push(s.error),
  });
  expect(result.state.phase).toBe("available");
  expect(cuts).toBe(1);
  expect(seen.some((e) => e?.includes("Envoi interrompu après 20 min"))).toBe(true);
});

test("a second cut at the same place stops the retries and says what to do", async () => {
  let clock = 0;
  let calls = 0;
  let cuts = 0;
  const result = await runTransfer(file("huge.mp4"), deps(async () => {
    calls += 1;
    clock += 1_200_000;
    throw cut();
  }), { folderId: null, idempotencyKey: "k", now: () => clock, onLongPutCut: () => { cuts += 1; } });
  expect(calls).toBe(2); // not 3: the engine does not loop for hours
  expect(cuts).toBe(2);
  expect(result.state.phase).toBe("failed");
  expect(result.state.failureKind).toBe("fatal"); // never replayed automatically
  expect(result.state.error).toContain("un par un");
  expect(result.state.error).toContain("TRAEFIK_READ_TIMEOUT");
});

test("a failure of the commit after a long upload is not mistaken for a cut", async () => {
  let clock = 0;
  let cuts = 0;
  let commits = 0;
  const d = deps(async () => { clock += 1_200_000; });
  d.commit = async (id) => {
    commits += 1;
    if (commits === 1) throw cut();
    return { id, status: "available", size_bytes: 10, checksum_sha256: "x" };
  };
  const result = await runTransfer(file("ok.mp4"), d, {
    folderId: null, idempotencyKey: "k", now: () => clock, onLongPutCut: () => { cuts += 1; },
  });
  expect(result.state.phase).toBe("available");
  expect(cuts).toBe(0);
});

test("in the queue, a cut drops the effective parallelism to one", async () => {
  const files = ["a", "b", "c", "d"].map((n) => file(`${n}.mp4`));
  const calls = new Map<string, number>();
  let running = 0;
  let peakAfterCut = 0;
  let cutSeen = false;
  const d = deps(async (_url, f) => {
    const name = (f as unknown as { name: string }).name;
    const n = (calls.get(name) ?? 0) + 1;
    calls.set(name, n);
    running += 1;
    if (cutSeen) peakAfterCut = Math.max(peakAfterCut, running);
    try {
      await new Promise((r) => setTimeout(r, 40));
      if (name === "a.mp4" && n === 1) throw cut(); // after 40 ms >= longPutMs (30 ms)
    } finally {
      running -= 1;
    }
  });
  const states: number[] = [];
  const queue = startUploadQueue(files, d, {
    folderId: null, concurrency: 4, startStaggerMs: 0,
    config: { longPutMs: 30, baseDelayMs: 1, maxDelayMs: 2 },
    onUpdate: (s) => {
      states.push(s.concurrency);
      if (s.concurrency === 1) cutSeen = true;
    },
  });
  const final = await queue.done;
  expect(final.done).toBe(4);
  expect(states).toContain(1); // the queue throttled itself to one at a time
});

test("setConcurrency applies to files that have not started, running ones continue", async () => {
  const files = Array.from({ length: 6 }, (_, i) => file(`f${i}.mp4`));
  const gates: Array<() => void> = [];
  let changed = false;
  let runningNew = 0;
  let peakNew = 0;
  let startedNew = 0;
  const d = deps(() => {
    const isNew = changed;
    if (isNew) {
      startedNew += 1;
      runningNew += 1;
      peakNew = Math.max(peakNew, runningNew);
    }
    return new Promise<void>((resolve) => {
      gates.push(() => {
        if (isNew) runningNew -= 1;
        resolve();
      });
    });
  });
  const queue = startUploadQueue(files, d, { folderId: null, concurrency: 4, startStaggerMs: 0 });
  for (let i = 0; i < 200 && gates.length < 4; i += 1) await new Promise((r) => setTimeout(r, 5));
  expect(gates.length).toBe(4); // four running at once
  changed = true;
  queue.setConcurrency(1);
  let finished = false;
  void queue.done.then(() => {
    finished = true;
  });
  // Release the four that were already running; the two left start one at a time.
  gates.splice(0, 4).forEach((release) => release());
  for (let i = 0; i < 400 && !finished; i += 1) {
    await new Promise((r) => setTimeout(r, 10));
    gates.shift()?.(); // finish the one new file that is running, if any
  }
  const final = await queue.done;
  expect(final.done).toBe(6);
  expect(startedNew).toBe(2);
  expect(peakNew).toBe(1); // after the change, one file at a time
});
