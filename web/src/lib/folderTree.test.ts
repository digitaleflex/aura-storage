import { describe, expect, it } from "vitest";
import { planFolders, resolvePlannedFolderIds, type ExistingFolderRef } from "./folderTree";

describe("resolvePlannedFolderIds", () => {
  it("orders nested folders parent-first and flags too-deep paths", () => {
    const plan = planFolders(["A/B/C/f.txt", "A/B/g.txt"], 2);
    expect(plan.folders.map((folder) => folder.path)).toEqual(["A", "A/B"]);
    expect(plan.folders[1]?.parentPath).toBe("A");
    expect(plan.tooDeep).toEqual(["A/B/C/f.txt"]);
  });

  it("does not resolve a nested folder through a new intermediate parent", () => {
    const tree: ExistingFolderRef[] = [
      { id: "photos", name: "Photos", parent_id: null },
      { id: "photos-sub", name: "Sub", parent_id: "photos" },
    ];
    const plan = planFolders([
      "New/Photos/img.jpg",
      "New/Photos/Sub/deep.jpg",
    ]);
    const resolved = resolvePlannedFolderIds(plan, tree, null);
    expect(resolved.has("New/Photos")).toBe(false);
    expect(resolved.has("New/Photos/Sub")).toBe(false);
    expect([...resolved.values()]).not.toContain("photos");
    expect([...resolved.values()]).not.toContain("photos-sub");
  });

  it("resolves a full existing chain including deep subfolders", () => {
    const tree: ExistingFolderRef[] = [
      { id: "photos", name: "Photos", parent_id: null },
      { id: "year", name: "2026", parent_id: "photos" },
      { id: "sub", name: "Sub", parent_id: "year" },
    ];
    const plan = planFolders(["Photos/2026/Sub/deep.jpg"]);
    const resolved = resolvePlannedFolderIds(plan, tree, null);
    expect(resolved.get("Photos")).toBe("photos");
    expect(resolved.get("Photos/2026")).toBe("year");
    expect(resolved.get("Photos/2026/Sub")).toBe("sub");
  });

  it("scopes a top-level match to the current destination folder", () => {
    const tree: ExistingFolderRef[] = [
      { id: "here", name: "Photos", parent_id: "current" },
      { id: "there", name: "Photos", parent_id: "other" },
    ];
    const plan = planFolders(["Photos/a.jpg"]);
    expect(resolvePlannedFolderIds(plan, tree, "current").get("Photos")).toBe("here");
  });
});
