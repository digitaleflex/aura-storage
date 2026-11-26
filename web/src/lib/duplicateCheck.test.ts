import { describe, expect, it, vi } from "vitest";
import {
  scanDuplicates,
  type DuplicateEntry,
  type ExistingObjectRef,
  type PreflightResult,
} from "./duplicateCheck";

function entry(key: string, name: string, content: string): DuplicateEntry {
  return { key, file: new File([content], name), rel: name };
}

async function checksum(content: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(content));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

describe("scanDuplicates", () => {
  it("emits progressive results and detects an existing name + size match", async () => {
    const file = entry("a", "rapport.pdf", "hello");
    const existing: ExistingObjectRef[] = [
      { id: "obj-1", display_name: "rapport.pdf", size_bytes: file.file.size },
    ];
    const seen: Array<[string, PreflightResult["status"]]> = [];

    const report = await scanDuplicates([file], new Map([["", existing]]), {
      hashAllUnderBytes: 0,
      onResult: (item, result) => seen.push([item.key, result.status]),
    });

    expect(seen).toEqual([["a", "checking"], ["a", "duplicate"]]);
    expect(report.matches).toHaveLength(1);
    expect(report.matches[0]).toMatchObject({
      key: "a",
      reason: "name_size",
      existing: { id: "obj-1" },
    });
    expect(report.results.get("a")?.status).toBe("duplicate");
  });

  it("confirms an existing checksum even when the file was renamed", async () => {
    const content = "contenu identique";
    const file = entry("a", "nouveau-nom.pdf", content);
    const existing: ExistingObjectRef[] = [
      {
        id: "obj-1",
        display_name: "ancien-nom.pdf",
        size_bytes: file.file.size,
        checksum_sha256: await checksum(content),
      },
    ];

    const report = await scanDuplicates([file], new Map([["", existing]]));

    expect(report.matches[0]).toMatchObject({ key: "a", reason: "checksum" });
    expect(report.matches[0]?.existing?.id).toBe("obj-1");
  });

  it("detects identical files inside the same import batch", async () => {
    const content = "même contenu";
    const files = [
      entry("a", "copie-a.pdf", content),
      entry("b", "copie-b.pdf", content),
    ];

    const report = await scanDuplicates(files, new Map());

    expect(report.results.get("a")?.status).toBe("ready");
    expect(report.results.get("b")?.status).toBe("duplicate");
    expect(report.matches[0]).toMatchObject({
      key: "b",
      reason: "batch_checksum",
      duplicateOf: "copie-a.pdf",
    });
  });

  it("keeps duplicates scoped to their destination folder", async () => {
    const content = "même contenu";
    const files = [
      { ...entry("a", "a.pdf", content), rel: "Dossier A/a.pdf" },
      { ...entry("b", "b.pdf", content), rel: "Dossier B/b.pdf" },
    ];

    const report = await scanDuplicates(files, new Map());

    expect(report.matches).toHaveLength(0);
    expect([...report.results.values()].every((result) => result.status === "ready")).toBe(true);
  });

  it("does not call different content a duplicate when checksums are known", async () => {
    const file = entry("a", "rapport.pdf", "nouveau contenu");
    const existing: ExistingObjectRef[] = [
      {
        id: "obj-1",
        display_name: "rapport.pdf",
        size_bytes: file.file.size,
        checksum_sha256: await checksum("ancien contenu"),
      },
    ];

    const report = await scanDuplicates([file], new Map([["", existing]]));

    expect(report.matches).toHaveLength(0);
    expect(report.results.get("a")?.status).toBe("ready");
  });

  it("marks a file as unverified when its required hash fails", async () => {
    const digest = vi.spyOn(crypto.subtle, "digest").mockRejectedValueOnce(new Error("hash failed"));
    const report = await scanDuplicates([entry("a", "a.pdf", "x")], new Map());
    expect(report.results.get("a")?.status).toBe("error");
    expect(report.matches).toHaveLength(0);
    digest.mockRestore();
  });

  it("stops when the scan is aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      scanDuplicates([entry("a", "a.pdf", "x")], new Map(), { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});
