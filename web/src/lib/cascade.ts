import { ApiError, api } from "./api";
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
  /** Catalogue status; a missing status is treated as deletable (older API). */
  status?: string;
}

/** One folder of the target subtree; the target itself is included. */
export interface CascadeFolder {
  id: string;
  name: string;
  parentId: string | null;
  path: string;
}

/** Une racine sélectionnée pour une suppression en cascade. */
export interface CascadeRoot {
  id: string;
  name: string;
}

/** The real content snapshot of a folder (never guessed, always listed). */
export interface CascadePlan {
  /** Première racine, conservé pour la compatibilité mono-dossier. */
  rootId: string;
  /** Nom de la racine unique, ou « N dossiers » pour une sélection multiple. */
  rootName: string;
  /** Racines réellement scannées (dédoublonnées : pas de dossier imbriqué).
   * Optionnel pour rester compatible avec d'anciens plans construits à la main. */
  roots?: CascadeRoot[];
  objects: CascadeObject[];
  folders: CascadeFolder[];
  fileCount: number;
  /** Descendant folders only: the target is not its own "subfolder". */
  folderCount: number;
  /** Objets vivants mais non supprimables (vérification en cours) : ils
   * bloquent la suppression du dossier côté serveur. */
  blockedCount?: number;
  /** Fichiers de la sélection situés hors des dossiers visés (flux batch). */
  extraFileCount?: number;
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
  /** Racines visées par le flux (une seule pour le cas mono-dossier). */
  roots: CascadeRoot[];
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

/**
 * Listings in flight at once. The edge allows 30 req/s on average (burst 60);
 * 4 requests at ~200 ms RTT is ~20 req/s, so a slow link is scanned quickly
 * without tripping the rate limit.
 */
export const SCAN_CONCURRENCY = 4;

/** Wait before the 2nd and 3rd attempt of one folder listing (3 total). */
const RETRY_DELAYS_MS = [250, 750] as const;

/** Statuses the API accepts for `DELETE /objects/{id}` (api/main.py:2255).
 * `verifying` is still a live object that blocks a folder delete, but the
 * endpoint refuses it: those files are counted as blocked, never planned. */
const DELETABLE_STATUSES = new Set(["available", "pending"]);

/** L'API refuse tout autre statut ; un statut absent (ancienne API) est
 * traité comme supprimable, comme avant. */
export function isDeletableStatus(status: string | undefined): boolean {
  return status === undefined || DELETABLE_STATUSES.has(status);
}

/**
 * A scan that could not be completed: carries the folder path so the dialog
 * can say *where* it stopped, and the underlying cause for the message.
 */
export class CascadeScanError extends Error {
  readonly path: string;
  override readonly cause: unknown;

  constructor(path: string, cause: unknown) {
    super(`Analyse interrompue dans « ${path} ».`);
    this.name = "CascadeScanError";
    this.path = path;
    this.cause = cause;
  }
}

/**
 * Whether retrying the same request may succeed: a fetch network failure
 * (`TypeError`), a rate limit (429) or a server fault (>= 500). Auth and
 * not-found errors are definitive and must fail fast.
 */
export function isTransientError(err: unknown): boolean {
  if (err instanceof TypeError) return true;
  if (err instanceof ApiError) return err.status === 429 || err.status >= 500;
  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/**
 * Run `fn` over `items` with at most `limit` calls in flight, preserving the
 * input order in the results. The first rejection stops new work (in-flight
 * calls are awaited, never cancelled) and is rethrown.
 */
export async function mapLimit<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  const width = Math.max(1, Math.min(limit, items.length));
  let next = 0;
  let failed = false;
  const worker = async (): Promise<void> => {
    while (!failed) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      try {
        results[index] = await fn(items[index] as T, index);
      } catch (err) {
        failed = true;
        throw err;
      }
    }
  };
  await Promise.all(Array.from({ length: width }, worker));
  return results;
}

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

/** One folder's objects, retried on transient failures only. */
async function fetchFolderObjectsResilient(
  folderId: string,
  path: string,
): Promise<ObjectItem[]> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await fetchFolderObjects(folderId);
    } catch (err) {
      const delay = RETRY_DELAYS_MS[attempt];
      if (delay === undefined || !isTransientError(err)) {
        throw new CascadeScanError(path, err);
      }
      await sleep(delay);
    }
  }
}

/**
 * Retire les racines déjà contenues dans une autre racine sélectionnée : un
 * dossier dont un ancêtre est aussi sélectionné ne doit être scanné qu'une fois.
 * La fonction est pure (hors réseau) pour être testable directement.
 */
export function dedupeCascadeRoots(
  roots: readonly CascadeRoot[],
  folders: readonly Pick<FolderItem, "id" | "parent_id">[],
): CascadeRoot[] {
  const parentOf = new Map(folders.map((folder) => [folder.id, folder.parent_id]));
  const selected = new Set(roots.map((root) => root.id));
  const seen = new Set<string>();
  const out: CascadeRoot[] = [];
  for (const root of roots) {
    if (seen.has(root.id)) continue;
    seen.add(root.id);
    // Remonte la chaîne des parents : un ancêtre sélectionné rend la racine
    // courante redondante (son contenu sera déjà scanné par cet ancêtre).
    let cursor = parentOf.get(root.id) ?? null;
    let nested = false;
    let guard = 0;
    while (cursor && guard < 64) {
      if (selected.has(cursor)) {
        nested = true;
        break;
      }
      cursor = parentOf.get(cursor) ?? null;
      guard += 1;
    }
    if (!nested) out.push(root);
  }
  return out;
}

/** Build the real content snapshot of one or many folders: descendant folders
 * and files, deduplicated when a root is already covered by another root. */
export async function scanCascadeMany(
  roots: readonly CascadeRoot[],
): Promise<CascadePlan> {
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
  // Une racine supprimée entre la sélection et le scan ne doit ni gonfler le
  // décompte, ni demander une confirmation pour zéro opération.
  const uniqueRoots = dedupeCascadeRoots(roots, all.items).filter((root) =>
    byId.has(root.id),
  );
  const folders: CascadeFolder[] = [];
  const seen = new Set<string>();
  for (const root of uniqueRoots) {
    const stack: string[] = [root.id];
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
  }
  const lists = await mapLimit(folders, SCAN_CONCURRENCY, (folder) =>
    fetchFolderObjectsResilient(folder.id, folder.path),
  );
  const objects: CascadeObject[] = [];
  const seenObjects = new Set<string>();
  let blockedCount = 0;
  for (let index = 0; index < folders.length; index += 1) {
    const folder = folders[index] as CascadeFolder;
    for (const item of lists[index] ?? []) {
      // `verifying` reste vivant côté serveur (il empêche la suppression du
      // dossier) mais l'API refuse de le supprimer : on le compte comme
      // bloquant au lieu de fabriquer deux 409 garantis.
      if (item.status === "verifying") {
        blockedCount += 1;
        continue;
      }
      // The API refuses to delete aborted/failed/expired/deleted leftovers;
      // planning them would abort the cascade on a 409 forever.
      if (!isDeletableStatus(item.status)) continue;
      if (seenObjects.has(item.id)) continue;
      seenObjects.add(item.id);
      objects.push({
        id: item.id,
        name: item.display_name,
        folderId: folder.id,
        path: folder.path,
        status: item.status,
      });
    }
  }
  return {
    rootId: uniqueRoots[0]?.id ?? "",
    rootName:
      uniqueRoots.length === 1
        ? uniqueRoots[0]?.name ?? ""
        : `${uniqueRoots.length} dossiers`,
    roots: uniqueRoots,
    objects,
    folders,
    fileCount: objects.length,
    folderCount: Math.max(0, folders.length - uniqueRoots.length),
    blockedCount,
  };
}

/** Build the real content snapshot of `rootId`: descendant folders + files. */
export async function scanCascade(rootId: string, rootName: string): Promise<CascadePlan> {
  return scanCascadeMany([{ id: rootId, name: rootName }]);
}

/** Flatten the snapshot into a leaf-first (post-order) list of delete steps:
 * a folder's files, its subfolders (recursively), then the folder itself, so
 * every folder is empty by the time its own DELETE is issued. Handles several
 * roots without visiting a shared subtree twice. */
export function planCascadeOpsForRoots(plan: CascadePlan): CascadeOp[] {
  const inTree = new Set(plan.folders.map((folder) => folder.id));
  const children = new Map<string, CascadeFolder[]>();
  for (const folder of plan.folders) {
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
  const visitedFolders = new Set<string>();
  const visitedObjects = new Set<string>();
  const visit = (folderId: string) => {
    if (visitedFolders.has(folderId)) return;
    visitedFolders.add(folderId);
    for (const object of objectsByFolder.get(folderId) ?? []) {
      if (visitedObjects.has(object.id)) continue;
      visitedObjects.add(object.id);
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
  const roots: CascadeRoot[] =
    plan.roots && plan.roots.length > 0
      ? plan.roots
      : [{ id: plan.rootId, name: plan.rootName }];
  for (const root of roots) visit(root.id);
  return ops;
}

/** Compatibilité mono-dossier : même ordre post-ordre, une seule racine. */
export function planCascadeOps(plan: CascadePlan): CascadeOp[] {
  return planCascadeOpsForRoots(plan);
}

/** Stable identity of a step, so a successful retry clears its failure entry. */
export function cascadeOpKey(op: { kind: string; id: string }): string {
  return `${op.kind}:${op.id}`;
}
