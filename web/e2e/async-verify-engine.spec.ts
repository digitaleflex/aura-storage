import { test, expect } from "@playwright/test";
import type { UploadIntentResponse } from "../src/lib/api";
import { ApiError, PresignedUploadError } from "../src/lib/api";
import { runTransfer, startUploadQueue } from "../src/lib/transfer";
import type { TransferDeps } from "../src/lib/transfer";

/**
 * N5 in the engine: a commit answered 202 "verifying" is followed until the
 * server says available or failed; success is never shown before that. A
 * resumed file the server already holds is not sent again.
 */

const FILE = new File([new Uint8Array(10)], "big.bin");

function intent(status = "pending"): UploadIntentResponse {
  return {
    id: "obj-v", status, method: "PUT", upload_url: status === "pending" ? "https://s3.test/put" : null,
    headers: {}, content_type: "application/octet-stream", size_bytes: FILE.size,
    expires_in: 900, expires_at: null, idempotent_replay: status !== "pending",
  };
}

function deps(states: string[], first = "pending") {
  let uploads = 0;
  let polls = 0;
  const phases: string[] = [];
  const d: TransferDeps = {
    requestIntent: async () => intent(first),
    upload: async () => {
      uploads += 1;
    },
    commit: async () => ({ id: "obj-v", status: "verifying", size_bytes: 10, checksum_sha256: "" }),
    abortIntent: async () => undefined,
    objectStatus: async () => {
      const status = states[Math.min(polls, states.length - 1)] ?? "verifying";
      polls += 1;
      return { status, checksum_sha256: status === "available" ? "abc" : "" };
    },
    sleep: async () => undefined,
    random: () => 0,
  };
  return { d, phases, counts: () => ({ uploads, polls }) };
}

test("a 202 commit is followed until the server marks the file available", async () => {
  const { d, counts } = deps(["verifying", "verifying", "available"]);
  const seen: string[] = [];
  const result = await runTransfer(FILE, d, {
    folderId: null, idempotencyKey: "k", onUpdate: (s) => seen.push(s.phase),
  });
  expect(result.state.phase).toBe("available");
  expect(result.checksum).toBe("abc");
  expect(counts().polls).toBe(3);
  // Never "available" before the last poll said so.
  expect(seen.indexOf("available")).toBe(seen.length - 1);
});

test("a failed integrity check ends the transfer as failed", async () => {
  const { d } = deps(["verifying", "failed"]);
  const result = await runTransfer(FILE, d, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("failed");
  expect(result.state.error).toContain("vérification");
});

test("a file the server already holds is not sent again", async () => {
  const { d, counts } = deps(["available"], "verifying");
  const result = await runTransfer(FILE, d, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("available");
  expect(counts().uploads).toBe(0);
});

test("a file waiting for its integrity check frees its upload slot", async () => {
  const files = ["a", "b", "c", "d"].map(
    (n) => ({ name: n, size: 10, type: "application/octet-stream" }) as unknown as File,
  );
  let uploading = 0;
  let peakUploading = 0;
  let uploadsStarted = 0;
  const releaseVerify: Array<() => void> = [];
  const d: TransferDeps = {
    requestIntent: async (input) => ({ ...intent(), id: input.fileName }),
    upload: async () => {
      uploadsStarted += 1;
      uploading += 1;
      peakUploading = Math.max(peakUploading, uploading);
      await new Promise((r) => setTimeout(r, 2));
      uploading -= 1;
    },
    commit: async (id) => ({ id, status: "verifying", size_bytes: 10, checksum_sha256: "" }),
    abortIntent: async () => undefined,
    // Verification only ends when the test says so.
    objectStatus: (id) =>
      new Promise((resolve) => {
        releaseVerify.push(() => resolve({ status: "available", checksum_sha256: id }));
      }),
    sleep: async () => undefined,
    random: () => 0,
  };
  const queue = startUploadQueue(files, d, { folderId: null, concurrency: 1, startStaggerMs: 0 });
  // With one slot, all four uploads still go out while every file is verifying.
  for (let i = 0; i < 400 && uploadsStarted < files.length; i += 1) {
    await new Promise((r) => setTimeout(r, 5));
  }
  expect(uploadsStarted).toBe(files.length);
  // The slot is released for verification only: uploads stay one at a time.
  expect(peakUploading).toBe(1);
  for (let i = 0; i < 400 && releaseVerify.length < files.length; i += 1) {
    await new Promise((r) => setTimeout(r, 5));
  }
  releaseVerify.forEach((release) => release());
  const final = await queue.done;
  expect(final.done).toBe(files.length);
  expect(final.failed).toBe(0);
});

test("a failing commit retries the commit, not the whole upload", async () => {
  let uploads = 0;
  let commits = 0;
  const d: TransferDeps = {
    requestIntent: async () => intent(),
    upload: async () => {
      uploads += 1;
    },
    commit: async () => {
      commits += 1;
      if (commits < 3) throw new ApiError(502, "bad gateway");
      return { id: "obj-v", status: "available", size_bytes: 10, checksum_sha256: "abc" };
    },
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };
  const result = await runTransfer(FILE, d, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("available");
  expect(uploads).toBe(1);
  expect(commits).toBe(3);
});

test("a 412 on the conditional PUT means the bytes are there: commit, do not fail", async () => {
  let commits = 0;
  const d: TransferDeps = {
    requestIntent: async () => intent(),
    upload: async () => {
      throw new PresignedUploadError("rejected", 412, "precondition failed");
    },
    commit: async () => {
      commits += 1;
      return { id: "obj-v", status: "available", size_bytes: 10, checksum_sha256: "abc" };
    },
    abortIntent: async () => undefined,
    sleep: async () => undefined,
    random: () => 0,
  };
  const result = await runTransfer(FILE, d, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("available");
  expect(commits).toBe(1);
});

test("the state says how long a phase lasts and what the server is doing", async () => {
  let clock = 1_000;
  const seen: Array<{ phase: string; mode?: string; since?: number }> = [];
  const { d } = deps(["verifying", "available"]);
  await runTransfer(FILE, d, {
    folderId: null, idempotencyKey: "k", now: () => (clock += 500),
    onUpdate: (s) => seen.push({ phase: s.phase, mode: s.verifyMode, since: s.phaseSince }),
  });
  const validating = seen.filter((s) => s.phase === "validating");
  // Inline while the commit re-reads the object, background once it is queued (202).
  expect(validating.some((s) => s.mode === "inline")).toBe(true);
  expect(validating.some((s) => s.mode === "background")).toBe(true);
  expect(validating.every((s) => typeof s.since === "number")).toBe(true);
  // The stamp moves forward at each phase change; 'available' carries no mode.
  const last = seen[seen.length - 1]!;
  expect(last.phase).toBe("available");
  expect(last.mode).toBeUndefined();
  expect(last.since!).toBeGreaterThan(validating[0]!.since!);
});

test("the state keeps every phase with its start time, and the server checksum", async () => {
  let clock = 0;
  const { d } = deps(["verifying", "available"]);
  const result = await runTransfer(FILE, d, {
    folderId: null, idempotencyKey: "k", now: () => (clock += 100),
  });
  const log = result.state.phaseLog ?? [];
  const phases = log.map((e) => e.phase);
  expect(phases[0]).toBe("requesting-intent");
  expect(phases).toContain("uploading");
  expect(phases).toContain("validating");
  expect(phases[phases.length - 1]).toBe("available");
  // Strictly increasing start times; a repeated validating poll is not a new step.
  expect(log.every((e, i) => i === 0 || e.at > log[i - 1]!.at)).toBe(true);
  expect(phases.filter((p) => p === "validating")).toHaveLength(1);
  expect(result.state.checksum).toBe("abc");
});
