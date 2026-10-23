import { describe, expect, it } from "vitest";
import {
  buildSessionDiagnostic,
  buildTransferDiagnostic,
  DIAGNOSTIC_SCHEMA,
  sanitizeDiagnosticText,
  SESSION_DIAGNOSTIC_SCHEMA,
} from "./diagnostics";
import type { QueueItem, QueueState } from "../../lib/transfer";

const ENV = {
  userAgent: "test-agent",
  language: "fr-FR",
  online: true,
  visibility: "visible",
  viewport: { width: 1280, height: 720 },
  devicePixelRatio: 1,
  timezone: "Europe/Paris",
};

function item(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "q-1",
    fileName: "rapport.pdf",
    sizeBytes: 100,
    paused: false,
    state: {
      phase: "failed",
      fileName: "rapport.pdf",
      sizeBytes: 100,
      transferredBytes: 40,
      progress: 0.4,
      attempts: 2,
      intentId: "obj-1",
      error:
        "Refus https://s3.example/bucket/key?X-Amz-Signature=abc Authorization: Bearer secrettoken",
      failureKind: "fatal",
      checksum: "",
      phaseSince: 1_700_000_002_000,
      phaseLog: [
        { phase: "requesting-intent", at: 1_700_000_000_000 },
        { phase: "uploading", at: 1_700_000_001_000 },
        { phase: "failed", at: 1_700_000_002_000 },
      ],
      ...overrides.state,
    },
  } as QueueItem;
}

function queue(items: QueueItem[]): QueueState {
  return {
    items,
    concurrency: 4,
    maxConcurrency: 4,
    active: 0,
    done: 0,
    failed: items.filter((i) => i.state.phase === "failed").length,
    cancelled: 0,
    paused: 0,
    schedulerPaused: false,
    finished: true,
  };
}

describe("sanitizeDiagnosticText", () => {
  it("redacts URLs, s3 URLs and token-like fields", () => {
    const result = sanitizeDiagnosticText(
      "Voir https://x/y?signature=1 puis s3://bucket/key Authorization: Bearer abc",
    );
    expect(result).not.toContain("https://");
    expect(result).not.toContain("s3://");
    expect(result).not.toContain("Bearer abc");
    expect(result).toContain("[redacted]");
  });
  it("returns null for empty values", () => {
    expect(sanitizeDiagnosticText("")).toBeNull();
    expect(sanitizeDiagnosticText(null)).toBeNull();
  });
});

describe("buildTransferDiagnostic", () => {
  it("includes real fields, ISO timestamps and no secrets", () => {
    const q = queue([item()]);
    const diagnostic = buildTransferDiagnostic(
      q.items[0]!,
      {
        queue: q,
        startedAt: 1_700_000_000_000,
        finishedAt: 1_700_000_003_000,
        throughput: 12,
        smoothedThroughput: 10,
        rateHistory: [8, 10, 12],
        itemRates: new Map([["q-1", 11]]),
        addedAtById: new Map([["q-1", 1_699_999_999_000]]),
        now: 1_700_000_004_000,
      },
      ENV,
    );
    expect(diagnostic.schema).toBe(DIAGNOSTIC_SCHEMA);
    expect(diagnostic.reportId).toBeTruthy();
    expect(diagnostic.file).toMatchObject({ name: "rapport.pdf", sizeBytes: 100 });
    expect(diagnostic.transfer).toMatchObject({
      status: "failed",
      failureKind: "fatal",
      attempts: 2,
      transferredBytes: 40,
    });
    expect(diagnostic.transfer.phaseLog).toHaveLength(3);
    expect(diagnostic.transfer.phaseLog[0]!.at).toBe("2023-11-14T22:13:20.000Z");
    expect(diagnostic.transfer.addedAt).toBe("2023-11-14T22:13:19.000Z");
    expect(diagnostic.session.counts.total).toBe(1);
    expect(JSON.stringify(diagnostic)).not.toContain("https://");
    expect(JSON.stringify(diagnostic)).not.toContain("secrettoken");
    expect(diagnostic.environment).toEqual(ENV);
  });

  it("describes a resumed multipart item and the session concurrency", () => {
    const resumed = item({
      state: {
        phase: "uploading",
        transferredBytes: 60,
        progress: 0.6,
        intentReplay: true,
        multipart: { partCount: 10, partSizeBytes: 10 },
        heldParts: 6,
        missingParts: 4,
        resumed: true,
      } as never,
    });
    const q = queue([resumed]);
    const diagnostic = buildSessionDiagnostic(
      q.items,
      {
        queue: q,
        startedAt: 1_700_000_000_000,
        finishedAt: null,
        throughput: 8,
        smoothedThroughput: 7,
        rateHistory: [0, 4, 8],
        itemRates: new Map([["q-1", 8]]),
        addedAtById: new Map([["q-1", 1_699_999_999_000]]),
        now: 1_700_000_010_000,
      },
      ENV,
    );
    expect(diagnostic.schema).toBe(SESSION_DIAGNOSTIC_SCHEMA);
    expect(diagnostic.items).toHaveLength(1);
    expect(diagnostic.items[0]).toMatchObject({
      resumed: true,
      intentReplay: true,
      heldParts: 6,
      missingParts: 4,
      itemRateBytesPerSecond: 8,
      multipart: { partCount: 10, partSizeBytes: 10 },
    });
    expect(diagnostic.session).toMatchObject({
      concurrency: 4,
      maxConcurrency: 4,
      rateHistoryBytesPerSecond: [0, 4, 8],
    });
  });

  it("keeps missing fields null instead of inventing values", () => {
    const q = queue([item({ state: {} as never })]);
    const diagnostic = buildTransferDiagnostic(
      q.items[0]!,
      {
        queue: q,
        startedAt: null,
        finishedAt: null,
        throughput: 0,
        smoothedThroughput: 0,
        rateHistory: [],
        itemRates: new Map(),
        addedAtById: new Map(),
        now: 0,
      },
      ENV,
    );
    expect(diagnostic.transfer.checksum).toBeNull();
    expect(diagnostic.transfer.commitTiming).toBeNull();
    expect(diagnostic.transfer.addedAt).toBeNull();
    expect(diagnostic.session.startedAt).toBeNull();
  });
});
