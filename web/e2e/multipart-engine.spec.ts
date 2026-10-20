import { test, expect } from "@playwright/test";
import { ApiError, PresignedUploadError } from "../src/lib/api";
import type { UploadIntentResponse } from "../src/lib/api";
import { runTransfer } from "../src/lib/transfer";
import type { TransferDeps } from "../src/lib/transfer";

/**
 * #72 multipart engine, unit level (no page, no server): parts are sent in
 * parallel, only missing parts are sent on resume, a failed part is retried
 * alone, an expired part URL is renewed, and a 409 at commit starts a new round.
 */

const PART = 8;
const FILE = new File([new Uint8Array(37)], "big.bin", { type: "application/octet-stream" });
const COUNT = 5;

function intent(): UploadIntentResponse {
  return {
    id: "obj-mp", status: "pending", method: "PUT", upload_mode: "multipart",
    upload_url: null, headers: {}, content_type: "application/octet-stream",
    size_bytes: FILE.size, multipart: { part_size_bytes: PART, part_count: COUNT },
    expires_in: 600000, expires_at: null, idempotent_replay: false,
  };
}

function setup(opts: {
  held?: number[][];
  failOnce?: Record<number, PresignedUploadError>;
  commitErrors?: number;
} = {}) {
  const sent: Array<{ part: number; size: number }> = [];
  const urlRequests: number[][] = [];
  let statusCalls = 0;
  let commits = 0;
  let aborts = 0;
  const failed = new Set<number>();
  const deps: TransferDeps = {
    requestIntent: async () => intent(),
    upload: async (url, blob, o) => {
      const part = Number(new URL(url).searchParams.get("partNumber"));
      const err = opts.failOnce?.[part];
      if (err && !failed.has(part)) {
        failed.add(part);
        throw err;
      }
      o.onProgress(blob.size, blob.size);
      sent.push({ part, size: blob.size });
    },
    commit: async () => {
      commits += 1;
      if (commits <= (opts.commitErrors ?? 0)) throw new ApiError(409, "1 part(s) missing");
      return { id: "obj-mp", status: "available", size_bytes: FILE.size, checksum_sha256: "abc", checksum_algorithm: "sha256" };
    },
    abortIntent: async () => {
      aborts += 1;
    },
    multipartStatus: async () => {
      const held = opts.held?.[statusCalls] ?? sent.map((s) => s.part);
      statusCalls += 1;
      return { id: "obj-mp", size_bytes: FILE.size, part_size_bytes: PART, part_count: COUNT, uploaded_parts: held };
    },
    partUrls: async (_id, numbers) => {
      urlRequests.push(numbers);
      return {
        id: "obj-mp", expires_in: 900,
        parts: numbers.map((n) => ({ part_number: n, size_bytes: 0, url: `https://s3.test/p?partNumber=${n}&v=${urlRequests.length}` })),
      };
    },
    sleep: async () => undefined,
    random: () => 0,
  };
  return { deps, sent, urlRequests, counts: () => ({ statusCalls, commits, aborts }) };
}

test("all parts are sent with their exact sizes, then the object is committed", async () => {
  const { deps, sent } = setup({ held: [[]] });
  const result = await runTransfer(FILE, deps, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("available");
  expect(sent.map((s) => s.part).sort()).toEqual([1, 2, 3, 4, 5]);
  expect(sent.find((s) => s.part === 5)?.size).toBe(5);
  expect(sent.filter((s) => s.part !== 5).every((s) => s.size === PART)).toBe(true);
  expect(result.state.transferredBytes).toBe(FILE.size);
});

test("a resumed upload sends only the parts the storage does not hold", async () => {
  const { deps, sent } = setup({ held: [[1, 2, 4]] });
  const result = await runTransfer(FILE, deps, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("available");
  expect(sent.map((s) => s.part).sort()).toEqual([3, 5]);
});

test("a failed part is retried alone", async () => {
  const { deps, sent } = setup({
    held: [[]],
    failOnce: { 3: new PresignedUploadError("network", 0, "Réseau interrompu.") },
  });
  const result = await runTransfer(FILE, deps, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("available");
  expect(sent.filter((s) => s.part === 3)).toHaveLength(1);
  expect(sent).toHaveLength(5);
  expect(result.state.attempts).toBe(1);
});

test("an expired part URL is renewed for that part", async () => {
  const { deps, urlRequests } = setup({
    held: [[]],
    failOnce: { 2: new PresignedUploadError("expired", 403, "Dépôt refusé (HTTP 403).") },
  });
  const result = await runTransfer(FILE, deps, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("available");
  expect(urlRequests.some((batch) => batch[0] === 2 && urlRequests.indexOf(batch) > 0)).toBe(true);
});

test("a 409 at commit asks again and sends the missing part", async () => {
  const { deps, sent, counts } = setup({ held: [[1, 2, 3, 4, 5], [1, 2, 4, 5]], commitErrors: 1 });
  const result = await runTransfer(FILE, deps, { folderId: null, idempotencyKey: "k" });
  expect(result.state.phase).toBe("available");
  expect(sent.map((s) => s.part)).toEqual([3]);
  expect(counts().statusCalls).toBe(2);
});

test("cancelling aborts the multipart session on the server", async () => {
  const controller = new AbortController();
  const { deps, counts } = setup({ held: [[]] });
  const upload = deps.upload;
  deps.upload = async (url, blob, o) => {
    controller.abort();
    await upload(url, blob, o);
  };
  const result = await runTransfer(FILE, deps, {
    folderId: null, idempotencyKey: "k", signal: controller.signal,
  });
  expect(result.state.phase).toBe("cancelled");
  expect(counts().aborts).toBe(1);
});

test("a rejected part fails the file without retrying it", async () => {
  const { deps, sent } = setup({
    held: [[]],
    failOnce: { 1: new PresignedUploadError("rejected", 400, "Dépôt refusé (HTTP 400).") },
  });
  const result = await runTransfer(FILE, deps, {
    folderId: null, idempotencyKey: "k", config: { partConcurrency: 1 },
  });
  expect(result.state.phase).toBe("failed");
  expect(sent).toHaveLength(0);
});
