import { test, expect } from "@playwright/test";
import {
  MAX_UPLOAD_DEPTH,
  normalizeRelativePath,
  parentDirOf,
  planFolders,
} from "../src/lib/folderTree";

/** Directory-upload planning (#64) — pure helpers, no DOM or network. */

test("normalizeRelativePath collapses separators and drops dot segments", () => {
  expect(normalizeRelativePath("Root\\a\\b.txt")).toBe("Root/a/b.txt");
  expect(normalizeRelativePath("/Root//a/./b.txt")).toBe("Root/a/b.txt");
  expect(normalizeRelativePath("../etc/passwd")).toBe("etc/passwd");
  expect(normalizeRelativePath("file.txt")).toBe("file.txt");
});

test("parentDirOf returns the containing directory or null at the root", () => {
  expect(parentDirOf("Root/a/b.txt")).toBe("Root/a");
  expect(parentDirOf("Root/b.txt")).toBe("Root");
  expect(parentDirOf("b.txt")).toBeNull();
});

test("planFolders lists unique folders, parents before children", () => {
  const plan = planFolders([
    "R/a/one.txt",
    "R/a/two.txt",
    "R/b.txt",
    "R/a/c/d.txt",
  ]);
  expect(plan.tooDeep).toEqual([]);
  expect(plan.folders.map((folder) => folder.path)).toEqual(["R", "R/a", "R/a/c"]);
  const byPath = Object.fromEntries(plan.folders.map((f) => [f.path, f]));
  expect(byPath["R"]?.parentPath).toBeNull();
  expect(byPath["R/a"]?.parentPath).toBe("R");
  expect(byPath["R/a/c"]?.parentPath).toBe("R/a");
});

test("planFolders refuses paths deeper than the cap", () => {
  const deep =
    Array.from({ length: MAX_UPLOAD_DEPTH + 1 }, (_, i) => `d${i}`).join("/") +
    "/f.txt";
  const plan = planFolders([deep, "ok/f.txt"]);
  expect(plan.tooDeep).toEqual([deep]);
  expect(plan.folders.map((folder) => folder.path)).toEqual(["ok"]);
});
