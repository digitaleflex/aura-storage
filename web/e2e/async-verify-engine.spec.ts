import { test, expect } from "@playwright/test";
import type { UploadIntentResponse } from "../src/lib/api";
import { runTransfer } from "../src/lib/transfer";
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
