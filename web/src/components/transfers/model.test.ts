import { describe, expect, it } from "vitest";
import {
  countTransfers,
  displayStatus,
  estimatedRemainingSeconds,
  failureTitle,
  fileCategory,
  filesPercent,
  idlePositions,
  matchesStatus,
  queuePositionLabel,
  scopeBytes,
  sortItems,
} from "./model";
import type { QueueItem, QueueState } from "../../lib/transfer";

function makeItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: overrides.id ?? "id-1",
    fileName: overrides.fileName ?? "file.pdf",
    sizeBytes: overrides.sizeBytes ?? 100,
    state: {
      phase: overrides.state?.phase ?? "idle",
      fileName: overrides.fileName ?? "file.pdf",
      sizeBytes: overrides.sizeBytes ?? 100,
      transferredBytes: overrides.state?.transferredBytes ?? 0,
      progress: overrides.state?.progress ?? 0,
      attempts: 0,
      intentId: null,
      error: overrides.state?.error ?? null,
      failureKind: overrides.state?.failureKind ?? undefined,
      checksum: "",
      phaseSince: 0,
      phaseLog: [],
    } as QueueItem["state"],
    paused: overrides.paused ?? false,
  };
}

function queue(items: QueueItem[]): QueueState {
  return {
    items,
    concurrency: 4,
    maxConcurrency: 4,
    active: 0,
    done: items.filter((i) => i.state.phase === "available").length,
    failed: items.filter((i) => i.state.phase === "failed").length,
    cancelled: items.filter((i) => i.state.phase === "cancelled").length,
    paused: 0,
    schedulerPaused: false,
    finished: false,
  };
}

describe("displayStatus", () => {
  it("maps idle to paused when the item is paused", () => {
    expect(displayStatus(makeItem({ paused: true }))).toBe("paused");
    expect(displayStatus(makeItem({ paused: false }))).toBe("queued");
  });
  it("maps engine phases to display statuses", () => {
    expect(displayStatus(makeItem({ state: { phase: "uploading" } as never }))).toBe("uploading");
    expect(displayStatus(makeItem({ state: { phase: "available" } as never }))).toBe("completed");
    expect(displayStatus(makeItem({ state: { phase: "failed" } as never }))).toBe("failed");
    expect(displayStatus(makeItem({ state: { phase: "cancelled" } as never }))).toBe("cancelled");
  });
});

describe("countTransfers", () => {
  it("excludes cancellations from the denominator", () => {
    const counts = countTransfers(
      queue([
        makeItem({ id: "a", state: { phase: "available" } as never }),
        makeItem({ id: "b", state: { phase: "cancelled" } as never }),
      ]),
    );
    expect(counts.total).toBe(2);
    expect(counts.completed).toBe(1);
    expect(counts.cancelled).toBe(1);
    expect(counts.denominator).toBe(1);
  });
});

describe("matchesStatus", () => {
  it("groups active phases under 'active'", () => {
    const item = makeItem({ state: { phase: "uploading" } as never });
    expect(matchesStatus(item, "active")).toBe(true);
    expect(matchesStatus(item, "queued")).toBe(false);
    expect(matchesStatus(item, "all")).toBe(true);
  });
});

describe("scopeBytes", () => {
  it("excludes cancelled items from both totals", () => {
    const result = scopeBytes(
      queue([
        makeItem({ id: "a", sizeBytes: 100, state: { phase: "uploading", transferredBytes: 40 } as never }),
        makeItem({ id: "b", sizeBytes: 50, state: { phase: "cancelled", transferredBytes: 50 } as never }),
      ]),
    );
    expect(result.totalBytes).toBe(100);
    expect(result.transferredBytes).toBe(40);
  });
});

describe("filesPercent", () => {
  it("returns 0 when the denominator is empty", () => {
    expect(filesPercent({ total: 2, active: 0, queued: 0, paused: 0, completed: 0, failed: 0, cancelled: 2, denominator: 0 })).toBe(0);
  });
  it("rounds completed over non-cancelled files", () => {
    expect(filesPercent({ total: 4, active: 0, queued: 0, paused: 0, completed: 2, failed: 0, cancelled: 0, denominator: 4 })).toBe(50);
  });
});

describe("estimatedRemainingSeconds", () => {
  it("returns null without rate, remaining bytes or activity", () => {
    const q = queue([makeItem({ id: "a", sizeBytes: 100, state: { phase: "uploading", transferredBytes: 40 } as never })]);
    expect(estimatedRemainingSeconds(q, 0)).toBeNull();
    const done = queue([makeItem({ id: "a", sizeBytes: 100, state: { phase: "available", transferredBytes: 100 } as never })]);
    expect(estimatedRemainingSeconds(done, 100)).toBeNull();
  });
  it("divides remaining bytes by the rate", () => {
    const q = queue([makeItem({ id: "a", sizeBytes: 100, state: { phase: "uploading", transferredBytes: 40 } as never })]);
    expect(estimatedRemainingSeconds(q, 10)).toBe(6);
  });
});

describe("sortItems", () => {
  it("sorts by name ascending and supports descending", () => {
    const items = [
      makeItem({ id: "a", fileName: "zeta.pdf" }),
      makeItem({ id: "b", fileName: "alpha.pdf" }),
    ];
    const asc = sortItems(items, "name", undefined, "asc").map((i) => i.fileName);
    const desc = sortItems(items, "name", undefined, "desc").map((i) => i.fileName);
    expect(asc).toEqual(["alpha.pdf", "zeta.pdf"]);
    expect(desc).toEqual(["zeta.pdf", "alpha.pdf"]);
  });
  it("sorts by size descending by default", () => {
    const items = [
      makeItem({ id: "a", sizeBytes: 10 }),
      makeItem({ id: "b", sizeBytes: 100 }),
    ];
    expect(sortItems(items, "size").map((i) => i.sizeBytes)).toEqual([100, 10]);
  });
});

describe("fileCategory", () => {
  it("classifies by extension", () => {
    expect(fileCategory("photo.JPG")).toBe("image");
    expect(fileCategory("clip.mp4")).toBe("video");
    expect(fileCategory("report.pdf")).toBe("pdf");
    expect(fileCategory("archive.zip")).toBe("archive");
    expect(fileCategory("track.mp3")).toBe("audio");
    expect(fileCategory("data.xyz")).toBe("other");
  });
});

describe("failureTitle", () => {
  it("maps failure kinds to French titles", () => {
    expect(failureTitle(makeItem({ state: { phase: "failed", failureKind: "fatal" } as never }))).toContain("refusé");
    expect(failureTitle(makeItem({ state: { phase: "failed", failureKind: "retryable" } as never }))).toContain("réseau");
  });
});

describe("idlePositions", () => {
  it("numbers only non-paused idle items", () => {
    const items = [
      makeItem({ id: "a", state: { phase: "idle" } as never, paused: false }),
      makeItem({ id: "b", state: { phase: "uploading" } as never }),
      makeItem({ id: "c", state: { phase: "idle" } as never, paused: true }),
      makeItem({ id: "d", state: { phase: "idle" } as never, paused: false }),
    ];
    const positions = idlePositions(queue(items));
    expect(positions.get("a")).toBe(0);
    expect(positions.get("d")).toBe(1);
    expect(positions.has("c")).toBe(false);
  });
});

describe("queuePositionLabel", () => {
  it("labels the next file, then its rank", () => {
    expect(queuePositionLabel(0)).toBe("Prochain dans la file");
    expect(queuePositionLabel(1)).toBe("2e dans la file");
  });
});
