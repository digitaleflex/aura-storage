import { test, expect } from "@playwright/test";
import {
  CascadeScanError,
  SCAN_CONCURRENCY,
  cascadeOpKey,
  mapLimit,
  planCascadeOps,
  scanCascade,
} from "../src/lib/cascade";
import type { CascadePlan } from "../src/lib/cascade";
import { ApiError, api } from "../src/lib/api";
import type { FolderItem, ObjectItem, ObjectQuery } from "../src/lib/api";

/**
 * The cascade deletion order is a safety property: the API refuses a folder
 * that still holds anything (409), so every file of a folder, and every
 * subfolder, must go before the folder itself. Pure logic, no browser.
 */

const plan: CascadePlan = {
  rootId: "root",
  rootName: "Racine",
  folders: [
    { id: "root", name: "Racine", parentId: null, path: "Racine" },
    { id: "a", name: "A", parentId: "root", path: "Racine / A" },
    { id: "a1", name: "A1", parentId: "a", path: "Racine / A / A1" },
    { id: "b", name: "B", parentId: "root", path: "Racine / B" },
  ],
  objects: [
    { id: "o-root", name: "r.pdf", folderId: "root", path: "Racine / r.pdf" },
    { id: "o-a1", name: "x.pdf", folderId: "a1", path: "Racine / A / A1 / x.pdf" },
    { id: "o-b", name: "y.pdf", folderId: "b", path: "Racine / B / y.pdf" },
  ],
  fileCount: 3,
  folderCount: 3,
};

test("every folder is removed after its files and subfolders, the target last", () => {
  const ops = planCascadeOps(plan);
  const order = ops.map((op) => `${op.kind}:${op.id}`);
  expect(order.at(-1)).toBe("folder:root");
  for (const folder of plan.folders) {
    const folderIndex = order.indexOf(`folder:${folder.id}`);
    expect(folderIndex).toBeGreaterThanOrEqual(0);
    for (const object of plan.objects.filter((o) => o.folderId === folder.id)) {
      expect(order.indexOf(`object:${object.id}`)).toBeLessThan(folderIndex);
    }
    for (const child of plan.folders.filter((f) => f.parentId === folder.id)) {
      expect(order.indexOf(`folder:${child.id}`)).toBeLessThan(folderIndex);
    }
  }
  // Nothing is dropped or duplicated: 3 files + 4 folders.
  expect(ops).toHaveLength(7);
  expect(new Set(order).size).toBe(7);
});

test("a folder outside the subtree is never planned", () => {
  const ops = planCascadeOps({
    ...plan,
    folders: [...plan.folders, { id: "stray", name: "S", parentId: "elsewhere", path: "S" }],
  });
  expect(ops.map((op) => op.id)).not.toContain("stray");
});

test("an operation's key is stable and distinguishes kinds", () => {
  expect(cascadeOpKey({ kind: "object", id: "1" })).toBe("object:1");
  expect(cascadeOpKey({ kind: "object", id: "1" })).not.toBe(cascadeOpKey({ kind: "folder", id: "1" }));
});

// -- Scanning under a real (stubbed) API -------------------------------------
// `api` is a plain mutable object, so its two read methods can be monkey-patched
// without touching production code or adding a mocking dependency.

const realListObjects = api.listObjects;
const realListAllFolders = api.listAllFolders;

test.afterEach(() => {
  api.listObjects = realListObjects;
  api.listAllFolders = realListAllFolders;
});

function folderItem(id: string, name: string, parentId: string | null): FolderItem {
  return { id, name, parent_id: parentId, created_at: 0 };
}

function objectItem(id: string, folderId: string, status: string | undefined): ObjectItem {
  return {
    id,
    display_name: `${id}.pdf`,
    content_type: "application/pdf",
    size_bytes: 1,
    checksum_sha256: "0".repeat(64),
    status: status as string,
    folder_id: folderId,
    created_at: 0,
    updated_at: 0,
  };
}

/** Flat tree: root with `children` direct subfolders, one object each. */
function stubTree(children: string[]): FolderItem[] {
  const folders = [
    folderItem("root", "Vault", null),
    ...children.map((id) => folderItem(id, id.toUpperCase(), "root")),
  ];
  api.listAllFolders = async () => ({ items: folders });
  return folders;
}

function stubObjects(
  byFolder: Record<string, ObjectItem[]>,
  onCall?: (folderId: string) => void,
): void {
  api.listObjects = async (query: ObjectQuery = {}) => {
    const folderId = query.folderId as string;
    onCall?.(folderId);
    await new Promise((resolve) => setTimeout(resolve, 5));
    return { items: byFolder[folderId] ?? [] };
  };
}

test("scan lists every folder once, with bounded concurrency and stable order", async () => {
  const children = ["a", "b", "c", "d", "e", "f"];
  stubTree(children);
  const calls: string[] = [];
  let inFlight = 0;
  let peak = 0;
  api.listObjects = async (query: ObjectQuery = {}) => {
    const folderId = query.folderId as string;
    calls.push(folderId);
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    await new Promise((resolve) => setTimeout(resolve, 10));
    inFlight -= 1;
    return { items: [objectItem(`o-${folderId}`, folderId, "available")] };
  };

  const scanned = await scanCascade("root", "Racine");

  expect(calls).toHaveLength(scanned.folders.length);
  expect(new Set(calls).size).toBe(scanned.folders.length);
  expect(peak).toBeGreaterThan(1);
  expect(peak).toBeLessThanOrEqual(SCAN_CONCURRENCY);
  // mapLimit preserved the folder order in the objects it returned.
  expect(scanned.objects.map((object) => object.folderId)).toEqual(
    scanned.folders.map((folder) => folder.id),
  );
  expect(scanned.fileCount).toBe(scanned.folders.length);
});

test("mapLimit keeps input order whatever the completion order", async () => {
  const delays = [30, 5, 15, 1, 25, 0];
  const out = await mapLimit([0, 1, 2, 3, 4, 5], 3, async (item) => {
    await new Promise((resolve) => setTimeout(resolve, delays[item] ?? 0));
    return item * 10;
  });
  expect(out).toEqual([0, 10, 20, 30, 40, 50]);
});

test("a transient failure is retried instead of aborting the scan", async () => {
  stubTree(["a", "b"]);
  const attempts: Record<string, number> = {};
  api.listObjects = async (query: ObjectQuery = {}) => {
    const folderId = query.folderId as string;
    attempts[folderId] = (attempts[folderId] ?? 0) + 1;
    if (folderId === "b" && attempts[folderId] === 1) {
      throw new TypeError("Failed to fetch");
    }
    return { items: [objectItem(`o-${folderId}`, folderId, "available")] };
  };

  const scanned = await scanCascade("root", "Racine");

  expect(attempts["b"]).toBe(2);
  expect(scanned.objects.map((object) => object.id)).toContain("o-b");
});

test("a 403 is definitive: one attempt, scan error names the folder", async () => {
  stubTree(["a", "forbidden"]);
  const attempts: Record<string, number> = {};
  api.listObjects = async (query: ObjectQuery = {}) => {
    const folderId = query.folderId as string;
    attempts[folderId] = (attempts[folderId] ?? 0) + 1;
    if (folderId === "forbidden") throw new ApiError(403, "forbidden");
    return { items: [] };
  };

  const failure = await scanCascade("root", "Racine").catch((err: unknown) => err);

  expect(failure).toBeInstanceOf(CascadeScanError);
  expect((failure as CascadeScanError).path).toBe("Racine / Vault / FORBIDDEN");
  expect((failure as CascadeScanError).cause).toBeInstanceOf(ApiError);
  expect(attempts["forbidden"]).toBe(1);
});

test("a server fault is tried three times, then reported as a scan error", async () => {
  stubTree(["a", "broken"]);
  const attempts: Record<string, number> = {};
  api.listObjects = async (query: ObjectQuery = {}) => {
    const folderId = query.folderId as string;
    attempts[folderId] = (attempts[folderId] ?? 0) + 1;
    if (folderId === "broken") throw new ApiError(503, "service unavailable");
    return { items: [] };
  };

  const failure = await scanCascade("root", "Racine").catch((err: unknown) => err);

  expect(failure).toBeInstanceOf(CascadeScanError);
  expect((failure as CascadeScanError).cause).toBeInstanceOf(ApiError);
  expect(attempts["broken"]).toBe(3);
});

test("the plan only holds objects the API can actually delete", async () => {
  stubTree([]);
  stubObjects({
    root: [
      objectItem("available", "root", "available"),
      objectItem("pending", "root", "pending"),
      objectItem("verifying", "root", "verifying"),
      objectItem("legacy", "root", undefined),
      objectItem("aborted", "root", "aborted"),
      objectItem("failed", "root", "failed"),
      objectItem("expired", "root", "expired"),
      objectItem("deleted", "root", "deleted"),
    ],
  });

  const scanned = await scanCascade("root", "Racine");

  expect(scanned.objects.map((object) => object.id)).toEqual([
    "available",
    "pending",
    "verifying",
    "legacy",
  ]);
  expect(scanned.fileCount).toBe(4);
  // The planned steps follow too: no doomed DELETE is ever issued.
  const ops = planCascadeOps(scanned);
  expect(ops.filter((op) => op.kind === "object").map((op) => op.id)).toEqual([
    "available",
    "pending",
    "verifying",
    "legacy",
  ]);
});
