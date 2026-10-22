import { test, expect } from "@playwright/test";
import { cascadeOpKey, planCascadeOps } from "../src/lib/cascade";
import type { CascadePlan } from "../src/lib/cascade";

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
  expect(cascadeOpKey({ kind: "folder", id: "1" })).not.toBe(cascadeOpKey({ kind: "object", id: "1" }));
});
