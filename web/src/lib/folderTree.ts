/**
 * Directory-upload planning (issue #64).
 *
 * Pure helpers that turn a flat list of file relative paths (from a
 * `webkitdirectory` selection or a dropped folder) into the set of folders that
 * must exist, ordered parent-before-child. Kept free of DOM/network so the
 * normalization and depth rules are unit-testable.
 */

/** A folder to create for a directory upload. */
export interface PlannedFolder {
  /** Normalized relative path, e.g. `Root/2026/a`. */
  path: string;
  /** Leaf label, e.g. `a`. */
  name: string;
  /** Parent path, or `null` for a top-level folder. */
  parentPath: string | null;
}

/** Depth cap for an imported tree (matches the catalogue folder limit). */
export const MAX_UPLOAD_DEPTH = 32;

/** Collapse separators, drop empty/`.`/`..` segments (no path traversal). */
export function normalizeRelativePath(value: string): string {
  return value
    .replace(/\\/g, "/")
    .split("/")
    .filter((part) => part !== "" && part !== "." && part !== "..")
    .join("/");
}

/** The directory that contains a relative file path, or `null` at the root. */
export function parentDirOf(relativePath: string): string | null {
  const parts = normalizeRelativePath(relativePath).split("/").filter(Boolean);
  const dirs = parts.slice(0, -1);
  return dirs.length ? dirs.join("/") : null;
}

export interface FolderPlan {
  /** Unique folders, parents before children. */
  folders: PlannedFolder[];
  /** File paths whose directory depth exceeds the cap (refused). */
  tooDeep: string[];
}

/** Minimal shape needed to match planned paths against existing folders. */
export interface ExistingFolderRef {
  id: string;
  name: string;
  parent_id: string | null;
}

function folderKey(parentId: string | null, name: string): string {
  return `${parentId ?? "root"}/${name}`;
}

/**
 * Resolve planned folder paths to existing folder ids without guessing.
 *
 * A nested folder can only match when its parent was itself resolved. If a
 * parent is new, every child below it is new too — falling back to the current
 * folder would compare against an unrelated folder with the same leaf name.
 */
export function resolvePlannedFolderIds(
  plan: FolderPlan,
  tree: readonly ExistingFolderRef[],
  currentFolderId: string | null,
): Map<string, string> {
  const existing = new Map<string, string>();
  for (const folder of tree) existing.set(folderKey(folder.parent_id, folder.name), folder.id);
  const resolved = new Map<string, string>();
  for (const folder of plan.folders) {
    const parentId = folder.parentPath ? resolved.get(folder.parentPath) : currentFolderId;
    if (folder.parentPath && !parentId) continue;
    const id = existing.get(folderKey(parentId ?? null, folder.name));
    if (id) resolved.set(folder.path, id);
  }
  return resolved;
}

/** Build the folder set for a set of file relative paths. */
export function planFolders(
  relativePaths: string[],
  maxDepth = MAX_UPLOAD_DEPTH,
): FolderPlan {
  const byPath = new Map<string, PlannedFolder>();
  const tooDeep: string[] = [];
  for (const raw of relativePaths) {
    const dirs = normalizeRelativePath(raw).split("/").filter(Boolean).slice(0, -1);
    if (dirs.length > maxDepth) {
      tooDeep.push(raw);
      continue;
    }
    let parent: string | null = null;
    let path = "";
    for (const name of dirs) {
      path = path ? `${path}/${name}` : name;
      if (!byPath.has(path)) byPath.set(path, { path, name, parentPath: parent });
      parent = path;
    }
  }
  const folders = [...byPath.values()].sort(
    (a, b) => a.path.split("/").length - b.path.split("/").length,
  );
  return { folders, tooDeep };
}
