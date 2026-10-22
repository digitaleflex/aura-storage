import { test, expect } from "@playwright/test";
import { ApiError, PresignedUploadError } from "../src/lib/api";
import type { CommitResponse, UploadIntentResponse } from "../src/lib/api";
import {
  DEFAULT_QUEUE_CONCURRENCY,
  backoffDelay,
  classifyError,
  runTransfer,
  startUploadQueue,
} from "../src/lib/transfer";
import type { QueueState, TransferDeps, TransferState } from "../src/lib/transfer";

/**
 * M03 transfer-engine unit tests.
 *
 * These run in the Playwright worker (no browser page, no servers): every side
 * effect of `runTransfer` is injected, so the state machine is exercised in
 * isolation. The page-level wiring is covered by upload-flow.spec.ts.
 */

const FILE = { name: "rapport.pdf", size: 1000, type: "application/pdf" } as unknown as File;

function makeIntent(overrides: Partial<UploadIntentResponse> = {}): UploadIntentResponse {
  return {
    id: "obj-1",
    status: "pending",
    method: "PUT",
    upload_url: "https://s3.example/put/obj-1",
    headers: { "Content-Type": "application/pdf" },
    content_type: "application/pdf",
    size_bytes: FILE.size,
    expires_in: 900,
    expires_at: null,
    idempotent_replay: false,
    ...overrides,
  };
}

function makeCommit(overrides: Partial<CommitResponse> = {}): CommitResponse {
  return {
    id: "obj-1",
    status: "available",
    size_bytes: FILE.size,
    checksum_sha256: "deadbeef",
    checksum_algorithm: "sha256",
    ...overrides,
  };
}

interface Recorder {
  intents: number;
  uploads: number;
  commits: number;
  aborts: number;
  keys: string[];
}

function makeDeps(config: {
  intent?: () => Promise<UploadIntentResponse>;
  upload?: (attempt: number) => Promise<void> | void;
  commit?: (attempt: number) => Promise<CommitResponse> | CommitResponse;
  abort?: () => Promise<void> | void;
} = {}): { deps: TransferDeps; rec: Recorder } {
  const rec: Recorder = { intents: 0, uploads: 0, commits: 0, aborts: 0, keys: [] };
  const deps: TransferDeps = {
    requestIntent: async (input) => {
      rec.intents += 1;
      rec.keys.push(input.idempotencyKey);
      return config.intent ? config.intent() : makeIntent();
    },
    upload: async () => {
      rec.uploads += 1;
      await config.upload?.(rec.uploads);
    },
    commit: async () => {
      rec.commits += 1;
      return config.commit ? config.commit(rec.commits) : makeCommit();
    },
    abortIntent: async () => {
      rec.aborts += 1;
      await config.abort?.();
    },
    sleep: async () => {
      /* no real waiting in tests */
    },
    random: () => 0,
  };
  return { deps, rec };
}

// ---------------------------------------------------------------------------
// Backoff with jitter
// ---------------------------------------------------------------------------
test("backoff grows exponentially, is capped and stays inside its jitter band", () => {
  const cfg = { baseDelayMs: 1000, maxDelayMs: 8000 };
  expect(backoffDelay(0, cfg, () => 0)).toBe(500); // half of 1000
  expect(backoffDelay(0, cfg, () => 1)).toBe(1000);
  expect(backoffDelay(1, cfg, () => 0)).toBe(1000); // half of 2000
  expect(backoffDelay(2, cfg, () => 0)).toBe(2000); // half of 4000
  expect(backoffDelay(3, cfg, () => 0)).toBe(4000); // half of the 8000 cap
  expect(backoffDelay(20, cfg, () => 1)).toBe(8000);
  for (let i = 0; i < 100; i += 1) {
    const delay = backoffDelay(6, cfg, () => Math.random());
    expect(delay).toBeGreaterThanOrEqual(4000);
    expect(delay).toBeLessThanOrEqual(8000);
  }
});

// ---------------------------------------------------------------------------
// Success only after the backend confirms
// ---------------------------------------------------------------------------
test("reports available with the backend checksum only after commit", async () => {
  const { deps, rec } = makeDeps();
  const phases: string[] = [];
  const result = await runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "k-success",
    onUpdate: (state) => phases.push(state.phase),
  });
  expect(result.state.phase).toBe("available");
  expect(result.objectId).toBe("obj-1");
  expect(result.checksum).toBe("deadbeef");
  expect(rec.intents).toBe(1);
  expect(rec.uploads).toBe(1);
  expect(rec.commits).toBe(1);
  expect(phases).toContain("requesting-intent");
  expect(phases).toContain("uploading");
  expect(phases).toContain("validating");
  expect(phases[phases.length - 1]).toBe("available");
});

test("upload progress is forwarded while the bytes move", async () => {
  const { deps } = makeDeps();
  const seen: number[] = [];
  const custom: TransferDeps = {
    ...deps,
    upload: async (_url, _file, opts) => {
      opts.onProgress(250, 1000);
      opts.onProgress(1000, 1000);
    },
  };
  const result = await runTransfer(FILE, custom, {
    folderId: null,
    idempotencyKey: "k-progress",
    onUpdate: (state) => {
      if (state.phase === "uploading") seen.push(state.progress);
    },
  });
  expect(result.state.phase).toBe("available");
  expect(seen).toContain(0.25);
  expect(seen).toContain(1);
});

// ---------------------------------------------------------------------------
// Controlled retries
// ---------------------------------------------------------------------------
test("retries a transient network failure, reusing the same intent and key", async () => {
  const { deps, rec } = makeDeps({
    upload: (attempt) => {
      if (attempt === 1) throw new PresignedUploadError("network", 0, "Réseau interrompu.");
    },
  });
  const result = await runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "k-retry",
  });
  expect(result.state.phase).toBe("available");
  expect(rec.uploads).toBe(2);
  expect(rec.intents).toBe(1);
  expect(rec.keys).toEqual(["k-retry"]);
  expect(result.state.attempts).toBe(1);
});

test("refreshes an expired presigned URL instead of failing the transfer", async () => {
  let issued = 0;
  const { deps, rec } = makeDeps({
    intent: async () => {
      issued += 1;
      return makeIntent({ id: `obj-${issued}`, upload_url: `https://s3.example/put/obj-${issued}` });
    },
    upload: (attempt) => {
      if (attempt === 1) throw new PresignedUploadError("expired", 403, "URL expirée.");
    },
  });
  const result = await runTransfer(FILE, deps, { folderId: null, idempotencyKey: "k-exp" });
  expect(result.state.phase).toBe("available");
  expect(rec.intents).toBe(2);
  expect(rec.uploads).toBe(2);
  expect(result.objectId).toBe("obj-2");
});

test("stops refreshing after the configured ceiling", async () => {
  const { deps, rec } = makeDeps({
    upload: () => {
      throw new PresignedUploadError("expired", 403, "URL expirée.");
    },
  });
  const result = await runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "k-exp-limit",
    config: { maxIntentRefreshes: 1 },
  });
  expect(result.state.phase).toBe("failed");
  expect(rec.intents).toBe(2); // initial + one refresh
});

// ---------------------------------------------------------------------------
// Validation errors and forced failures never fake success
// ---------------------------------------------------------------------------
test("a validation error fails without retry or success", async () => {
  const { deps, rec } = makeDeps({
    commit: () => {
      throw new ApiError(422, "uploaded size does not match storage");
    },
  });
  const result = await runTransfer(FILE, deps, { folderId: null, idempotencyKey: "k-422" });
  expect(result.state.phase).toBe("failed");
  expect(result.state.error).toContain("incomplet ou différent de l'original");
  expect(rec.commits).toBe(1);
});

test("never reports available while commit keeps failing", async () => {
  const { deps } = makeDeps({
    commit: () => {
      throw new ApiError(503, "storage unavailable");
    },
  });
  const result = await runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "k-503",
    config: { maxAttempts: 2 },
  });
  expect(result.state.phase).toBe("failed");
  expect(result.state.attempts).toBe(1);
});

// ---------------------------------------------------------------------------
// Cancellation is a real backend abortion
// ---------------------------------------------------------------------------
test("cancellation aborts the backend intent and reports cancelled", async () => {
  const controller = new AbortController();
  const { deps, rec } = makeDeps({
    upload: () => {
      controller.abort();
      throw new PresignedUploadError("aborted", 0, "Transfert annulé.");
    },
  });
  const result = await runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "k-abort",
    signal: controller.signal,
  });
  expect(result.state.phase).toBe("cancelled");
  expect(result.objectId).toBe("obj-1");
  expect(rec.aborts).toBe(1);
  expect(rec.commits).toBe(0);
});

test("a pre-aborted transfer never requests an intent", async () => {
  const controller = new AbortController();
  controller.abort();
  const { deps, rec } = makeDeps();
  const result = await runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "k-pre",
    signal: controller.signal,
  });
  expect(result.state.phase).toBe("cancelled");
  expect(rec.intents).toBe(0);
});

test("a cancel racing a failed intent request still ends as cancelled", async () => {
  const controller = new AbortController();
  const { deps } = makeDeps({
    intent: async () => {
      controller.abort();
      throw new ApiError(500, "storage unavailable");
    },
  });
  const result = await runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "k-race",
    signal: controller.signal,
  });
  expect(result.state.phase).toBe("cancelled");
});

// ---------------------------------------------------------------------------
// Error classification
// ---------------------------------------------------------------------------
test("classifyError maps transport and API errors to retry decisions", () => {
  expect(classifyError(new PresignedUploadError("network", 0, "x"))).toBe("retryable");
  expect(classifyError(new PresignedUploadError("expired", 403, "x"))).toBe("expired");
  expect(classifyError(new PresignedUploadError("aborted", 0, "x"))).toBe("aborted");
  expect(classifyError(new PresignedUploadError("rejected", 400, "x"))).toBe("fatal");
  expect(classifyError(new ApiError(503, "x"))).toBe("retryable");
  expect(classifyError(new ApiError(410, "x"))).toBe("retryable");
  expect(classifyError(new ApiError(403, "x"))).toBe("expired");
  expect(classifyError(new ApiError(404, "x"))).toBe("fatal");
  expect(classifyError(new Error("boom"))).toBe("fatal");
});

test("the transfer state is always shaped for the UI", async () => {
  const { deps } = makeDeps();
  const states: TransferState[] = [];
  await runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "k-shape",
    onUpdate: (state) => states.push(state),
  });
  for (const state of states) {
    expect(state.fileName).toBe("rapport.pdf");
    expect(state.sizeBytes).toBe(1000);
    expect(state.transferredBytes).toBeGreaterThanOrEqual(0);
    expect(state.progress).toBeGreaterThanOrEqual(0);
    expect(state.progress).toBeLessThanOrEqual(1);
  }
});

// ---------------------------------------------------------------------------
// Multi-file queue (#63): bounded concurrency, failure isolation, retry
// ---------------------------------------------------------------------------
function fakeFile(name: string, size = 10): File {
  return { name, size, type: "application/octet-stream" } as unknown as File;
}

async function waitFor(predicate: () => boolean, tries = 300): Promise<void> {
  for (let i = 0; i < tries; i += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  throw new Error("condition not met in time");
}

test("queue transfers every file with bounded concurrency", async () => {
  const files = ["a.bin", "b.bin", "c.bin", "d.bin", "e.bin"].map((n) => fakeFile(n));
  const gates: Array<() => void> = [];
  const deps: TransferDeps = {
    requestIntent: async (input) => ({
      id: input.fileName,
      status: "pending",
      method: "PUT",
      upload_url: "https://s3.example/put",
      headers: { "Content-Type": "application/octet-stream" },
      content_type: "application/octet-stream",
      size_bytes: input.sizeBytes,
      expires_in: 900,
      expires_at: null,
      idempotent_replay: false,
    }),
    // Hold each upload open until the test releases it.
    upload: () => new Promise<void>((resolve) => gates.push(resolve)),
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const states: QueueState[] = [];
  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 2,
    onUpdate: (state) => states.push(state),
  });

  let peak = 0;
  for (let i = 0; i < files.length; i += 1) {
    await waitFor(() => gates.length > 0);
    peak = Math.max(peak, gates.length);
    gates.shift()?.();
  }
  const final = await queue.done;

  expect(final.done).toBe(files.length);
  expect(final.failed).toBe(0);
  expect(final.finished).toBe(true);
  expect(peak).toBeLessThanOrEqual(2);
  // It never started more than the configured concurrency at once.
  expect(Math.max(...states.map((s) => s.active))).toBeLessThanOrEqual(2);
});

test("default queue concurrency stays narrow so one uplink is not split ten ways", async () => {
  expect(DEFAULT_QUEUE_CONCURRENCY).toBeLessThanOrEqual(4);
  const files = Array.from({ length: 12 }, (_, i) => fakeFile(`f${i}.bin`));
  let running = 0;
  let peak = 0;
  const deps: TransferDeps = {
    requestIntent: async (input) => ({
      id: input.fileName,
      status: "pending",
      method: "PUT",
      upload_url: "https://s3.example/put",
      headers: { "Content-Type": "application/octet-stream" },
      content_type: "application/octet-stream",
      size_bytes: input.sizeBytes,
      expires_in: 900,
      expires_at: null,
      idempotent_replay: false,
    }),
    upload: async () => {
      running += 1;
      peak = Math.max(peak, running);
      await new Promise((r) => setTimeout(r, 5));
      running -= 1;
    },
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };
  const final = await startUploadQueue(files, deps, { folderId: null }).done;
  expect(final.done).toBe(files.length);
  expect(peak).toBeLessThanOrEqual(DEFAULT_QUEUE_CONCURRENCY);
});

test("one failing file does not stop the others, and retry re-runs only it", async () => {
  const files = [fakeFile("ok.bin"), fakeFile("bad.bin"), fakeFile("ok2.bin")];
  let badCommitAttempts = 0;
  let badCommitCalls = 0;
  let okCommitCalls = 0;
  const deps: TransferDeps = {
    requestIntent: async (input) => ({
      id: input.fileName,
      status: "pending",
      method: "PUT",
      upload_url: "https://s3.example/put",
      headers: { "Content-Type": "application/octet-stream" },
      content_type: "application/octet-stream",
      size_bytes: input.sizeBytes,
      expires_in: 900,
      expires_at: null,
      idempotent_replay: false,
    }),
    upload: async () => undefined,
    commit: async (id) => {
      if (id === "bad.bin") {
        badCommitCalls += 1;
        badCommitAttempts += 1;
        if (badCommitAttempts === 1) throw new ApiError(422, "size mismatch");
      } else {
        okCommitCalls += 1;
      }
      return { id, status: "available", size_bytes: 1, checksum_sha256: "x" };
    },
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const states: QueueState[] = [];
  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 2,
    onUpdate: (state) => states.push(state),
  });

  const firstPass = await queue.done;
  expect(firstPass.done).toBe(2);
  expect(firstPass.failed).toBe(1);
  expect(okCommitCalls).toBe(2); // the two good files committed once each

  // Retry: only the failed file is re-run; the two successes are untouched.
  queue.retryFailed();
  await waitFor(() => states[states.length - 1]?.done === 3);
  expect(badCommitCalls).toBe(2);
  expect(okCommitCalls).toBe(2);
  expect(states[states.length - 1]?.failed).toBe(0);
});

test("cancelAll stops the queue and marks the unsettled files cancelled", async () => {
  const files = [fakeFile("a.bin"), fakeFile("b.bin")];
  const deps: TransferDeps = {
    requestIntent: async (input) => ({
      id: input.fileName,
      status: "pending",
      method: "PUT",
      upload_url: "https://s3.example/put",
      headers: { "Content-Type": "application/octet-stream" },
      content_type: "application/octet-stream",
      size_bytes: input.sizeBytes,
      expires_in: 900,
      expires_at: null,
      idempotent_replay: false,
    }),
    // Uploads honour the abort signal so cancellation can settle them.
    upload: (_url, _file, opts) =>
      new Promise<void>((_resolve, reject) => {
        const fail = () => reject(new PresignedUploadError("aborted", 0, "annulé"));
        if (opts.signal?.aborted) fail();
        else opts.signal?.addEventListener("abort", fail, { once: true });
      }),
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const queue = startUploadQueue(files, deps, { folderId: null, concurrency: 1 });
  await waitFor(() => true);
  queue.cancelAll();
  const final = await queue.done;
  expect(final.cancelled).toBe(files.length);
  expect(final.done).toBe(0);
  expect(final.finished).toBe(true);
});

test("queue honours each entry's target folder (default when omitted)", async () => {
  const folders: Array<string | null> = [];
  const deps: TransferDeps = {
    requestIntent: async (input) => {
      folders.push(input.folderId);
      return {
        id: input.fileName,
        status: "pending",
        method: "PUT",
        upload_url: "https://s3.example/put",
        headers: { "Content-Type": "application/octet-stream" },
        content_type: "application/octet-stream",
        size_bytes: input.sizeBytes,
        expires_in: 900,
        expires_at: null,
        idempotent_replay: false,
      };
    },
    upload: async () => undefined,
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const queue = startUploadQueue(
    [
      { file: fakeFile("a.txt"), folderId: "F1" },
      { file: fakeFile("b.txt"), folderId: null },
      { file: fakeFile("c.txt") },
    ],
    deps,
    { folderId: "DEFAULT", concurrency: 1 },
  );
  const final = await queue.done;

  expect(final.done).toBe(3);
  expect(new Set(folders)).toEqual(new Set(["F1", null, "DEFAULT"]));
});

// ---------------------------------------------------------------------------
// Adaptive parallelism + paced starts (JDownLoader-inspired, M03 follow-up)
// ---------------------------------------------------------------------------
function queueIntent(input: {
  fileName: string;
  sizeBytes: number;
}): UploadIntentResponse {
  return {
    id: input.fileName,
    status: "pending",
    method: "PUT",
    upload_url: "https://s3.example/put",
    headers: { "Content-Type": "application/octet-stream" },
    content_type: "application/octet-stream",
    size_bytes: input.sizeBytes,
    expires_in: 900,
    expires_at: null,
    idempotent_replay: false,
  };
}

test("queue shrinks parallelism after repeated congestion failures", async () => {
  const files = ["a.bin", "b.bin", "c.bin", "d.bin", "e.bin"].map((n) => fakeFile(n));
  let uploads = 0;
  const deps: TransferDeps = {
    requestIntent: async (input) => queueIntent(input),
    upload: async () => {
      uploads += 1;
      throw new PresignedUploadError("network", 0, "Réseau interrompu.");
    },
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const states: QueueState[] = [];
  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 3,
    onUpdate: (state) => states.push(state),
  });
  const final = await queue.done;

  expect(final.failed).toBe(files.length);
  expect(final.done).toBe(0);
  // 3 files x 3 internal attempts each: every attempt really ran.
  expect(uploads).toBe(files.length * 3);
  // Two consecutive congestion failures cost one slot each: 3 -> 2 -> 1.
  expect(final.concurrency).toBe(1);
  expect(states.some((s) => s.concurrency === 2)).toBe(true);
  // The initial burst never exceeded the configured maximum.
  expect(Math.max(...states.map((s) => s.active))).toBeLessThanOrEqual(3);
});

test("queue restores parallelism after sustained success", async () => {
  const files = ["bad1.bin", "bad2.bin", "ok1.bin", "ok2.bin", "ok3.bin"].map((n) => fakeFile(n));
  let releaseOks: () => void = () => undefined;
  const okGate = new Promise<void>((resolve) => {
    releaseOks = resolve;
  });
  const deps: TransferDeps = {
    requestIntent: async (input) => queueIntent(input),
    upload: async (_url, file) => {
      if ((file as File).name.startsWith("bad")) {
        throw new PresignedUploadError("network", 0, "Réseau interrompu.");
      }
      await okGate;
    },
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const states: QueueState[] = [];
  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 2,
    onUpdate: (state) => states.push(state),
  });

  // Hold the good files back so both congestion failures settle first.
  await waitFor(() => states[states.length - 1]?.failed === 2);
  expect(states[states.length - 1]?.concurrency).toBe(1);
  releaseOks();
  const final = await queue.done;

  expect(final.failed).toBe(2);
  expect(final.done).toBe(3);
  // Three consecutive successes restored the second slot.
  expect(final.concurrency).toBe(2);
});

test("fatal errors do not shrink parallelism", async () => {
  const files = ["a.bin", "b.bin", "c.bin"].map((n) => fakeFile(n));
  const deps: TransferDeps = {
    requestIntent: async (input) => queueIntent(input),
    upload: async () => undefined,
    commit: async () => {
      throw new ApiError(422, "uploaded size does not match storage");
    },
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const queue = startUploadQueue(files, deps, { folderId: null, concurrency: 2 });
  const final = await queue.done;

  expect(final.failed).toBe(files.length);
  // A 422 is a rejected file, not a congested link: no adaptation.
  expect(final.concurrency).toBe(2);
});

test("parallel starts are staggered by default", async () => {
  const files = [fakeFile("a.bin"), fakeFile("b.bin")];
  const sleeps: number[] = [];
  const deps: TransferDeps = {
    requestIntent: async (input) => queueIntent(input),
    upload: async () => undefined,
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async (ms) => {
      sleeps.push(ms);
    },
    random: () => 0,
  };

  const queue = startUploadQueue(files, deps, { folderId: null, concurrency: 2 });
  const final = await queue.done;

  expect(final.done).toBe(2);
  // The first file starts at once, the second after the stagger delay; a
  // successful transfer never sleeps for backoff, so this is the stagger.
  expect(sleeps).toEqual([250]);
});

test("startStaggerMs 0 disables pacing", async () => {
  const files = [fakeFile("a.bin"), fakeFile("b.bin")];
  const sleeps: number[] = [];
  const deps: TransferDeps = {
    requestIntent: async (input) => queueIntent(input),
    upload: async () => undefined,
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async (ms) => {
      sleeps.push(ms);
    },
    random: () => 0,
  };

  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 2,
    startStaggerMs: 0,
  });
  const final = await queue.done;

  expect(final.done).toBe(2);
  expect(sleeps).toEqual([]);
});

// ---------------------------------------------------------------------------
// Per-file retry
// ---------------------------------------------------------------------------
test("retryItem re-runs only the chosen failed file with a fresh key", async () => {
  const files = [fakeFile("ok.bin"), fakeFile("bad.bin")];
  let badUploads = 0;
  const keys: string[] = [];
  const deps: TransferDeps = {
    requestIntent: async (input) => {
      keys.push(input.idempotencyKey);
      return queueIntent(input);
    },
    upload: async (_url, file) => {
      if ((file as File).name === "bad.bin") {
        badUploads += 1;
        // Fail every internal attempt of the first submission only.
        if (badUploads <= 3) throw new PresignedUploadError("network", 0, "Réseau interrompu.");
      }
    },
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const states: QueueState[] = [];
  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 2,
    startStaggerMs: 0,
    onUpdate: (state) => states.push(state),
  });
  const firstPass = await queue.done;
  expect(firstPass.done).toBe(1);
  expect(firstPass.failed).toBe(1);

  const badItem = states[states.length - 1]?.items.find((i) => i.fileName === "bad.bin");
  expect(badItem?.state.phase).toBe("failed");
  queue.retryItem(badItem!.id);
  // `done` already resolved on the first pass: follow the live snapshots.
  await waitFor(() => states[states.length - 1]?.done === 2);
  const final = states[states.length - 1]!;

  expect(final.done).toBe(2);
  expect(final.failed).toBe(0);
  // The retried file minted a fresh idempotency key; the success was untouched.
  expect(new Set(keys).size).toBe(keys.length);
  expect(keys.length).toBe(3); // ok.bin x1, bad.bin x2
});

test("retryItem ignores unknown, active and successful files", async () => {
  const files = [fakeFile("ok.bin"), fakeFile("bad.bin")];
  let badUploads = 0;
  const deps: TransferDeps = {
    requestIntent: async (input) => queueIntent(input),
    upload: async (_url, file) => {
      if ((file as File).name === "bad.bin") {
        badUploads += 1;
        throw new PresignedUploadError("network", 0, "Réseau interrompu.");
      }
    },
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const states: QueueState[] = [];
  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 1,
    startStaggerMs: 0,
    onUpdate: (state) => states.push(state),
  });

  // Unknown id: no-op, the queue keeps running.
  queue.retryItem("no-such-id");
  const firstPass = await queue.done;
  expect(firstPass.done).toBe(1);
  expect(firstPass.failed).toBe(1);
  expect(badUploads).toBe(3);

  const last = states[states.length - 1]!;
  const okId = last.items.find((i) => i.fileName === "ok.bin")!.id;
  const badId = last.items.find((i) => i.fileName === "bad.bin")!.id;
  // A successful file can never restart.
  queue.retryItem(okId);
  expect(states[states.length - 1]?.done).toBe(1);
  // Retrying the failed file re-runs it (and fails again here); the
  // success is untouched.
  queue.retryItem(badId);
  await waitFor(() => badUploads === 6);
  await waitFor(() => states[states.length - 1]?.failed === 1);
  expect(states[states.length - 1]?.done).toBe(1);
});

test("snapshots expose the configured ceiling next to the effective value", async () => {
  const files = [fakeFile("a.bin")];
  const deps: TransferDeps = {
    requestIntent: async (input) => queueIntent(input),
    upload: async () => undefined,
    commit: async (id) => ({ id, status: "available", size_bytes: 1, checksum_sha256: "x" }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const states: QueueState[] = [];
  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 3,
    startStaggerMs: 0,
    onUpdate: (state) => states.push(state),
  });
  const final = await queue.done;

  expect(final.concurrency).toBe(3);
  expect(final.maxConcurrency).toBe(3);
  expect(states.every((s) => s.maxConcurrency === 3)).toBe(true);
});

// ---------------------------------------------------------------------------
// Automatic replay after a connectivity loss
// ---------------------------------------------------------------------------
test("a failed transfer records why it stopped", async () => {
  const down = makeDeps({
    upload: () => {
      throw new PresignedUploadError("network", 0, "Réseau interrompu.");
    },
  });
  const dropped = await runTransfer(FILE, down.deps, {
    folderId: null,
    idempotencyKey: "k-drop",
  });
  expect(dropped.state.phase).toBe("failed");
  expect(dropped.state.failureKind).toBe("retryable");

  const refused = makeDeps({
    commit: () => {
      throw new ApiError(507, "storage capacity reached");
    },
  });
  const full = await runTransfer(FILE, refused.deps, {
    folderId: null,
    idempotencyKey: "k-full",
  });
  expect(full.state.phase).toBe("failed");
  expect(full.state.failureKind).toBe("fatal");
});

test("retryTransient replays transient failures only, and reports the count", async () => {
  const files = [fakeFile("drop.bin"), fakeFile("full.bin")];
  let linkDown = true;
  const autoRetried: number[] = [];
  const states: QueueState[] = [];
  const deps: TransferDeps = {
    requestIntent: async (input) => ({
      id: input.fileName,
      status: "pending",
      method: "PUT",
      upload_url: `https://s3.example/put/${input.fileName}`,
      headers: { "Content-Type": "application/octet-stream" },
      content_type: "application/octet-stream",
      size_bytes: input.sizeBytes,
      expires_in: 900,
      expires_at: null,
      idempotent_replay: false,
    }),
    upload: async (url) => {
      if (linkDown && url.endsWith("/drop.bin")) {
        throw new PresignedUploadError("network", 0, "Réseau interrompu.");
      }
    },
    commit: async (id) => {
      if (id === "full.bin") throw new ApiError(507, "storage capacity reached");
      return { id, status: "available", size_bytes: 10, checksum_sha256: "x" };
    },
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const queue = startUploadQueue(files, deps, {
    folderId: null,
    concurrency: 2,
    onUpdate: (state) => states.push(state),
    onAutoRetry: (count) => autoRetried.push(count),
  });

  const first = await queue.done;
  expect(first.done).toBe(0);
  expect(first.failed).toBe(2);
  expect(
    first.items.find((item) => item.fileName === "drop.bin")?.state.failureKind,
  ).toBe("retryable");
  expect(
    first.items.find((item) => item.fileName === "full.bin")?.state.failureKind,
  ).toBe("fatal");

  // The link is back: only the network failure is replayed; the rejected one
  // would fail identically and stays in the tray for a human decision.
  linkDown = false;
  queue.retryTransient();
  await waitFor(() => states[states.length - 1]?.done === 1 && states[states.length - 1]?.active === 0);

  const last = states[states.length - 1]!;
  expect(last.done).toBe(1);
  expect(last.failed).toBe(1);
  expect(last.items.find((item) => item.fileName === "drop.bin")?.state.phase).toBe(
    "available",
  );
  expect(last.items.find((item) => item.fileName === "full.bin")?.state.phase).toBe(
    "failed",
  );
  expect(autoRetried).toEqual([1]);
});

test("retryTransient stops after maxReconnectRetries for the same file", async () => {
  const states: QueueState[] = [];
  let uploads = 0;
  const deps: TransferDeps = {
    requestIntent: async (input) => ({
      id: input.fileName,
      status: "pending",
      method: "PUT",
      upload_url: `https://s3.example/put/${input.fileName}`,
      headers: { "Content-Type": "application/octet-stream" },
      content_type: "application/octet-stream",
      size_bytes: input.sizeBytes,
      expires_in: 900,
      expires_at: null,
      idempotent_replay: false,
    }),
    upload: async () => {
      uploads += 1;
      throw new PresignedUploadError("network", 0, "Réseau interrompu.");
    },
    commit: async (id) => ({
      id,
      status: "available",
      size_bytes: 10,
      checksum_sha256: "x",
    }),
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };

  const queue = startUploadQueue([fakeFile("drop.bin")], deps, {
    folderId: null,
    maxReconnectRetries: 2,
    onUpdate: (state) => states.push(state),
  });
  await queue.done;
  // One run = maxAttempts PUTs (default 3).
  expect(uploads).toBe(3);

  for (let attempt = 0; attempt < 2; attempt += 1) {
    queue.retryTransient();
    await waitFor(
      () =>
        states[states.length - 1]?.active === 0 &&
        states[states.length - 1]?.items[0]?.state.phase === "failed",
    );
  }
  expect(uploads).toBe(9); // 3 runs, then the cap holds

  // A manual retry resets the budget and runs again.
  queue.retryFailed();
  await waitFor(() => states[states.length - 1]?.active === 0 && uploads === 12);
  expect(uploads).toBe(12);
});

test("the online event replays a transient failure without any click", async () => {
  // Node has no `window`: install the smallest event target the queue uses so
  // the browser-lifecycle wiring (offline pause, online replay) is exercised
  // exactly as in the page. The page-level twin lives in upload-reconnect.spec.ts.
  const listeners = new Map<string, Array<() => void>>();
  const fakeWindow = {
    addEventListener: (type: string, handler: () => void) => {
      listeners.set(type, [...(listeners.get(type) ?? []), handler]);
    },
    removeEventListener: (type: string, handler: () => void) => {
      listeners.set(type, (listeners.get(type) ?? []).filter((h) => h !== handler));
    },
  };
  const globals = globalThis as unknown as { window?: unknown };
  const hadWindow = "window" in globals;
  const previousWindow = globals.window;
  globals.window = fakeWindow;

  try {
    let linkDown = true;
    const autoRetried: number[] = [];
    const states: QueueState[] = [];
    const deps: TransferDeps = {
      requestIntent: async (input) => ({
        id: input.fileName,
        status: "pending",
        method: "PUT",
        upload_url: `https://s3.example/put/${input.fileName}`,
        headers: { "Content-Type": "application/octet-stream" },
        content_type: "application/octet-stream",
        size_bytes: input.sizeBytes,
        expires_in: 900,
        expires_at: null,
        idempotent_replay: false,
      }),
      upload: async () => {
        if (linkDown) throw new PresignedUploadError("network", 0, "Réseau interrompu.");
      },
      commit: async (id) => ({
        id,
        status: "available",
        size_bytes: 10,
        checksum_sha256: "x",
      }),
      abortIntent: async () => undefined,
      sleep: async () => undefined,
      random: () => 0,
    };

    const queue = startUploadQueue([fakeFile("drop.bin")], deps, {
      folderId: null,
      onUpdate: (state) => states.push(state),
      onAutoRetry: (count) => autoRetried.push(count),
    });

    const first = await queue.done;
    expect(first.failed).toBe(1);
    // The queue is "finished" but must keep listening: a cut is recoverable.
    expect(listeners.get("online")?.length ?? 0).toBeGreaterThan(0);

    const fire = (type: string) => {
      for (const handler of listeners.get(type) ?? []) handler();
    };

    fire("offline");
    expect(states[states.length - 1]?.schedulerPaused).toBe(true);

    linkDown = false;
    fire("online");
    await waitFor(
      () =>
        states[states.length - 1]?.active === 0 &&
        states[states.length - 1]?.done === 1,
    );

    const last = states[states.length - 1]!;
    expect(last.done).toBe(1);
    expect(last.failed).toBe(0);
    expect(autoRetried).toEqual([1]);
    expect(states.some((state) => state.schedulerPaused)).toBe(true);
  } finally {
    if (hadWindow) globals.window = previousWindow;
    else delete globals.window;
  }
});
