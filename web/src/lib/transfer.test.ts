import { describe, expect, it, vi } from "vitest";
import { ApiError, PresignedUploadError } from "./api";
import type { CommitResponse, UploadIntentResponse } from "./api";
import { runTransfer } from "./transfer";
import type { TransferDeps, TransferState } from "./transfer";

const FILE = { name: "gros.bin", size: 1000, type: "application/octet-stream" } as unknown as File;

function makeIntent(overrides: Partial<UploadIntentResponse> = {}): UploadIntentResponse {
  return {
    id: "obj-1",
    status: "pending",
    method: "PUT",
    upload_url: "https://s3.example/put/obj-1",
    headers: { "Content-Type": "application/octet-stream" },
    content_type: "application/octet-stream",
    size_bytes: FILE.size,
    expires_in: 900,
    expires_at: null,
    idempotent_replay: false,
    ...overrides,
  };
}

function makeDeps(overrides: Partial<TransferDeps> = {}): TransferDeps {
  return {
    requestIntent: async () => makeIntent(),
    upload: async () => {},
    commit: async () => ({ status: "available", checksum_sha256: "abc" }) as CommitResponse,
    abortIntent: async () => {},
    sleep: async () => {},
    random: () => 0,
    ...overrides,
  };
}

function run(deps: TransferDeps, config: Record<string, unknown> = {}, states: TransferState[] = []) {
  return runTransfer(FILE, deps, {
    folderId: null,
    idempotencyKey: "key-1",
    config,
    onUpdate: (state) => states.push(state),
  });
}

describe("runTransfer — bounded verification follow-up", () => {
  it("gives up after maxVerifyPolls instead of holding a slot forever", async () => {
    const objectStatus = vi.fn(async () => ({ status: "verifying" }));
    const deps = makeDeps({
      commit: async () => ({ status: "verifying" }) as CommitResponse,
      objectStatus,
    });

    const result = await run(deps, { maxVerifyPolls: 3 });

    expect(objectStatus).toHaveBeenCalledTimes(3);
    expect(result.state.phase).toBe("failed");
    expect(result.state.error).toContain("3 contrôles");
    expect(result.state.failureKind).toBe("fatal");
  });

  it("still accepts a late 'available' verdict", async () => {
    const objectStatus = vi.fn()
      .mockResolvedValueOnce({ status: "verifying" })
      .mockResolvedValueOnce({ status: "available", checksum_sha256: "abc" });
    const deps = makeDeps({
      commit: async () => ({ status: "verifying" }) as CommitResponse,
      objectStatus,
    });

    const result = await run(deps, { maxVerifyPolls: 5 });

    expect(result.state.phase).toBe("available");
    expect(objectStatus).toHaveBeenCalledTimes(2);
  });
});

describe("runTransfer — retry feedback", () => {
  it("clears a transient error as soon as bytes progress again", async () => {
    const states: TransferState[] = [];
    let uploads = 0;
    const deps = makeDeps({
      upload: async (_url, _blob, opts) => {
        uploads += 1;
        if (uploads === 1) throw new PresignedUploadError("network", 0, "Réseau interrompu.");
        opts.onProgress(500, 1000);
      },
    });

    const result = await run(deps, { maxAttempts: 2 }, states);

    expect(states.some((s) => s.error === "Connexion au stockage interrompue.")).toBe(true);
    expect(states.some((s) => s.phase === "uploading" && s.error === null)).toBe(true);
    expect(result.state.phase).toBe("available");
    expect(result.state.error).toBe(null);
  });

  it("gives control-plane calls maxAttempts retries, not partMaxAttempts", async () => {
    const multipartStatus = vi.fn(async () => {
      throw new ApiError(503, "storage busy");
    });
    const deps = makeDeps({
      requestIntent: async () => makeIntent({
        upload_mode: "multipart",
        multipart: { part_count: 1, part_size_bytes: 1000 },
      }),
      multipartStatus,
      partUrls: async () => ({ id: "obj-1", expires_in: 900, parts: [] }),
    });

    const result = await run(deps, { maxAttempts: 2, partMaxAttempts: 6 });

    expect(multipartStatus).toHaveBeenCalledTimes(2);
    expect(result.state.phase).toBe("failed");
  });
});
