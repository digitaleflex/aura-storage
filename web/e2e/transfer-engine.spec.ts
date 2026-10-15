import { test, expect } from "@playwright/test";
import { ApiError, PresignedUploadError } from "../src/lib/api";
import type { CommitResponse, UploadIntentResponse } from "../src/lib/api";
import { backoffDelay, classifyError, runTransfer } from "../src/lib/transfer";
import type { TransferDeps, TransferState } from "../src/lib/transfer";

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
  expect(result.state.error).toContain("does not match");
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
