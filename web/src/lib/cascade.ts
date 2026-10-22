import { api } from "./api";
import type { FolderItem, ObjectItem } from "./api";

// -- Recursive (cascade) folder deletion ------------------------------------
// The server refuses a folder that still holds files or subfolders (409). The
// only sanctioned way to delete such a folder is to empty it explicitly: this
// flow removes every object of the subtree, then the now-empty folders from the
// leaves up to the target. Nothing is ever reported as deleted until the API
// confirms it, and nothing is removed without an explicit confirmation.

/** One file in the target subtree, resolved through real list requests. */
export interface CascadeObject {
  id: string;
  name: string;
  folderId: string;
  /** Human path ("Racine / Dossier / Sous-dossier"). */
  path: string;
}

/** One folder of the target subtree; the target itself is included. */
export interface CascadeFolder {
  id: string;
  name: string;
  parentId: string | null;
  path: string;
}

/** The real content snapshot of a folder (never guessed, always listed). */
export interface CascadePlan {
  rootId: string;
  rootName: string;
  objects: CascadeObject[];
  folders: CascadeFolder[];
  fileCount: number;
  /** Descendant folders only: the target is not its own "subfolder". */
  folderCount: number;
}

/** One delete step, ordered so a folder is emptied before it is removed. */
export interface CascadeOp {
  kind: "object" | "folder";
  id: string;
  label: string;
  path: string;
}

/** A step that failed; kept so the user can retry or abandon it explicitly. */
export interface CascadeFailure {
  key: string;
  kind: "object" | "folder";
  id: string;
  label: string;
  path: string;
  error: string;
}

export type CascadePhase = "scanning" | "confirm" | "deleting" | "done";

export interface CascadeState {
  rootId: string;
  rootName: string;
  phase: CascadePhase;
  plan: CascadePlan | null;
  ops: CascadeOp[];
  done: number;
  /** Path of the item currently being processed (live progress). */
  current: string | null;
  failures: CascadeFailure[];
  cancelled: boolean;
  scanError: string | null;
}

/** The server caps `limit` at 100; page until a short page comes back. */
export const CASCADE_PAGE_SIZE = 100;

/** Every object filed directly in one folder, across all pages. */
export async function fetchFolderObjects(folderId: string): Promise<ObjectItem[]> {
  const out: ObjectItem[] = [];
  let offset = 0;
  // Hard guard: a server that ignores `offset` can never spin forever.
  for (let guard = 0; guard < 1000; guard += 1) {
    const page = await api.listObjects({
      folderId,
      limit: CASCADE_PAGE_SIZE,
      offset,
    });
    out.push(...page.items);
    if (page.items.length < CASCADE_PAGE_SIZE) break;
    offset += page.items.length;
  }
  return out;
}

/** Build the real content snapshot of `rootId`: descendant folders + files. */
export async function scanCascade(rootId: string, rootName: string): Promise<CascadePlan> {
  const all = await api.listAllFolders();
  const byId = new Map(all.items.map((folder) => [folder.id, folder]));
  const childMap = new Map<string | null, FolderItem[]>();
  for (const folder of all.items) {
    const key = folder.parent_id ?? null;
    const bucket = childMap.get(key);
    if (bucket) bucket.push(folder);
    else childMap.set(key, [folder]);
  }
  const pathOf = (id: string): string => {
    const names: string[] = [];
    let cursor: string | null = id;
    let guard = 0;
    while (cursor && guard < 64) {
      const folder: FolderItem | undefined = byId.get(cursor);
      if (!folder) break;
      names.unshift(folder.name);
      cursor = folder.parent_id;
      guard += 1;
    }
    return ["Racine", ...names].join(" / ");
  };
  const folders: CascadeFolder[] = [];
  const seen = new Set<string>();
  const stack: string[] = [rootId];
  while (stack.length > 0) {
    const id = stack.pop();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const folder = byId.get(id);
    if (!folder) continue;
    folders.push({
      id,
      name: folder.name,
      parentId: folder.parent_id,
      path: pathOf(id),
    });
    for (const child of childMap.get(id) ?? []) stack.push(child.id);
  }
  const objects: CascadeObject[] = [];
  for (const folder of folders) {
    const list = await fetchFolderObjects(folder.id);
    for (const item of list) {
      objects.push({
        id: item.id,
        name: item.display_name,
        folderId: folder.id,
        path: folder.path,
      });
    }
  }
  return {
    rootId,
    rootName,
    objects,
    folders,
    fileCount: objects.length,
    folderCount: Math.max(0, folders.length - 1),
  };
}

/** Flatten the snapshot into a leaf-first (post-order) list of delete steps:
 * a folder's files, its subfolders (recursively), then the folder itself, so
 * every folder is empty by the time its own DELETE is issued. */
export function planCascadeOps(plan: CascadePlan): CascadeOp[] {
  const inTree = new Set(plan.folders.map((folder) => folder.id));
  const children = new Map<string, CascadeFolder[]>();
  for (const folder of plan.folders) {
    if (folder.id === plan.rootId) continue;
    const parent = folder.parentId;
    if (!parent || !inTree.has(parent)) continue;
    const bucket = children.get(parent);
    if (bucket) bucket.push(folder);
    else children.set(parent, [folder]);
  }
  const objectsByFolder = new Map<string, CascadeObject[]>();
  for (const object of plan.objects) {
    const bucket = objectsByFolder.get(object.folderId);
    if (bucket) bucket.push(object);
    else objectsByFolder.set(object.folderId, [object]);
  }
  const byId = new Map(plan.folders.map((folder) => [folder.id, folder]));
  const ops: CascadeOp[] = [];
  const visit = (folderId: string) => {
    for (const object of objectsByFolder.get(folderId) ?? []) {
      ops.push({
        kind: "object",
        id: object.id,
        label: object.name,
        path: object.path,
      });
    }
    for (const child of children.get(folderId) ?? []) visit(child.id);
    const self = byId.get(folderId);
    if (self) {
      ops.push({ kind: "folder", id: self.id, label: self.name, path: self.path });
    }
  };
  visit(plan.rootId);
  return ops;
}

/** Stable identity of a step, so a successful retry clears its failure entry. */
export function cascadeOpKey(op: { kind: string; id: string }): string {
  return `${op.kind}:${op.id}`;
}
