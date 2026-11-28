import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, PresignedUploadError } from "./api";
import type { CommitResponse, UploadIntentResponse } from "./api";
import { classifyError, runTransfer, startUploadQueue } from "./transfer";
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

describe("classifyError — expiry is not a permission refusal", () => {
  it("keeps an expired S3 URL replayable but treats an API 403 as final", () => {
    expect(classifyError(new PresignedUploadError("rejected", 403, "AccessDenied"))).toBe("expired");
    expect(classifyError(new PresignedUploadError("expired", 403, "URL expirée."))).toBe("expired");
    // The API answered "Action non autorisée": renewing the URL cannot help.
    expect(classifyError(new ApiError(403, "forbidden"))).toBe("fatal");
  });
});

describe("runTransfer — bounded verification follow-up", () => {
  it("leaves a replayable outcome after maxVerifyPolls instead of holding a slot forever", async () => {
    const objectStatus = vi.fn(async () => ({ status: "verifying" }));
    const deps = makeDeps({
      commit: async () => ({ status: "verifying" }) as CommitResponse,
      objectStatus,
    });

    const result = await run(deps, { maxVerifyPolls: 3 });

    expect(objectStatus).toHaveBeenCalledTimes(3);
    expect(result.state.phase).toBe("failed");
    expect(result.state.error).toContain("3 contrôles");
    // The server has not refused anything: the object is stored and queued for
    // the check, so the queue may resume watching it automatically.
    expect(result.state.failureKind).toBe("verify-timeout");
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

describe("startUploadQueue — automatic batch retry", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function file(name: string): File {
    return { name, size: 10, type: "application/octet-stream" } as File;
  }

  function options(onAutoRetry: (count: number) => void) {
    return {
      folderId: null,
      // One transport failure is terminal at transfer level, so the replay has
      // to come from the queue, not from runTransfer's own bounded attempts.
      config: { maxAttempts: 1 },
      startStaggerMs: 0,
      adaptiveConcurrency: false,
      autoRetryFailures: true,
      autoRetryDelayMs: 50,
      maxAutoRetries: 1,
      onAutoRetry,
    };
  }

  it("replays all retryable failures together without a click", async () => {
    vi.useFakeTimers();
    const attempts = new Map<string, number>();
    const deps = makeDeps({
      upload: async (_url, blob) => {
        const name = (blob as File).name;
        const count = (attempts.get(name) ?? 0) + 1;
        attempts.set(name, count);
        if (count === 1) throw new PresignedUploadError("network", 0, "Réseau interrompu.");
      },
    });
    const onAutoRetry = vi.fn();
    const queue = startUploadQueue([file("a.bin"), file("b.bin")], deps, options(onAutoRetry));

    await vi.advanceTimersByTimeAsync(0);
    expect(onAutoRetry).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(50);
    expect(onAutoRetry).toHaveBeenCalledTimes(1);
    expect(onAutoRetry).toHaveBeenCalledWith(2);
    await vi.advanceTimersByTimeAsync(0);

    const final = await queue.done;
    expect(final.items.map((item) => item.state.phase)).toEqual(["available", "available"]);
  });

  it("replays a verification timeout without resending the bytes", async () => {
    vi.useFakeTimers();
    const objectStatus = vi.fn(async () => ({ status: "verifying" }));
    const upload = vi.fn(async () => {});
    const keys: string[] = [];
    let intents = 0;
    const deps = makeDeps({
      // The replay carries the same idempotency key: the API answers with the
      // object already being verified, not with a second upload URL.
      requestIntent: async (input) => {
        keys.push(input.idempotencyKey);
        return intents++ === 0
          ? makeIntent()
          : makeIntent({ status: "verifying", upload_url: null });
      },
      commit: async () => ({ status: "verifying" }) as CommitResponse,
      objectStatus,
      upload,
    });
    const onAutoRetry = vi.fn();
    const queue = startUploadQueue([file("a.bin")], deps, {
      ...options(onAutoRetry),
      config: { maxAttempts: 1, maxVerifyPolls: 1 },
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(50);
    await vi.advanceTimersByTimeAsync(0);

    expect(onAutoRetry).toHaveBeenCalledTimes(1);
    // The bytes were already stored by the first attempt: the replay only
    // resumes the server-side verification, under the same idempotency key.
    expect(upload).toHaveBeenCalledTimes(1);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    const final = await queue.done;
    expect(final.items[0]?.state.failureKind).toBe("verify-timeout");
  });

  it("stops at maxAutoRetries instead of looping forever", async () => {
    vi.useFakeTimers();
    const deps = makeDeps({
      upload: async () => {
        throw new PresignedUploadError("rejected", 503, "Indisponible.");
      },
    });
    const onAutoRetry = vi.fn();
    const queue = startUploadQueue([file("a.bin")], deps, options(onAutoRetry));

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(50);
    await vi.advanceTimersByTimeAsync(0);

    expect(onAutoRetry).toHaveBeenCalledTimes(1);
    const final = await queue.done;
    expect(final.items[0]?.state.phase).toBe("failed");
  });

  it("never replays a fatal rejection", async () => {
    vi.useFakeTimers();
    const upload = vi.fn(async () => {
      throw new ApiError(507, "Stockage plein.");
    });
    const onAutoRetry = vi.fn();
    const queue = startUploadQueue([file("a.bin")], makeDeps({ upload }), options(onAutoRetry));

    await vi.advanceTimersByTimeAsync(0);

    expect(onAutoRetry).not.toHaveBeenCalled();
    const final = await queue.done;
    expect(final.items[0]?.state.phase).toBe("failed");
    expect(upload).toHaveBeenCalledTimes(1);
  });
});
