import { afterEach, describe, expect, it, vi } from "vitest";
import { PresignedUploadError, putToPresignedUrl } from "./api";

/**
 * The presigned PUT used to arm XHR's *total* `timeout` (120 s), which killed
 * any slow-but-progressing part. These tests pin the rearmed idle deadline:
 * bytes keep flowing, only silence ends the transfer.
 */
class FakeXHR {
  static last: FakeXHR | null = null;
  timeout = -1;
  status = 200;
  responseText = "";
  aborted = false;
  upload = { onprogress: null as ((event: { loaded: number; total: number }) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXHR.last = this;
  }

  open(): void {}
  setRequestHeader(): void {}
  send(): void {}
  abort(): void {
    this.aborted = true;
    this.onabort?.();
  }
  progress(loaded: number): void {
    this.upload.onprogress?.({ loaded, total: 1000 });
  }
  succeed(): void {
    this.onload?.();
  }
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FakeXHR.last = null;
});

function start(timeoutMs?: number): Promise<void> {
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  return putToPresignedUrl("https://s3.example/put", new Blob(["x"]), { timeoutMs });
}

describe("putToPresignedUrl idle deadline", () => {
  it("does not use XHR's total timeout", async () => {
    vi.useFakeTimers();
    const promise = start();
    expect(FakeXHR.last?.timeout).toBe(0);
    FakeXHR.last?.succeed();
    await expect(promise).resolves.toBeUndefined();
  });

  it("stays alive while progress events keep arriving", async () => {
    vi.useFakeTimers();
    const promise = start(1_000);
    const xhr = FakeXHR.last!;
    const rejected = expect(promise).rejects.toBeInstanceOf(PresignedUploadError);
    for (let i = 1; i <= 6; i += 1) {
      vi.advanceTimersByTime(900);
      xhr.progress(i * 100);
    }
    // 6 × 900 ms = 5.4 s without a single 1 s gap of silence: no timeout.
    expect(xhr.aborted).toBe(false);
    vi.advanceTimersByTime(1_000);
    await rejected;
    expect(xhr.aborted).toBe(true);
  });

  it("fails with a retryable error after an idle gap", async () => {
    vi.useFakeTimers();
    const promise = start(500);
    const rejected = expect(promise).rejects.toMatchObject({
      kind: "network",
      message: "Délai dépassé.",
    });
    vi.advanceTimersByTime(500);
    await rejected;
  });

  it("a completed PUT leaves no timer behind", async () => {
    vi.useFakeTimers();
    const promise = start(500);
    FakeXHR.last?.succeed();
    await expect(promise).resolves.toBeUndefined();
    vi.advanceTimersByTime(5_000);
    expect(FakeXHR.last?.aborted).toBe(false);
  });
});
