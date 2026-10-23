/**
 * Remember the files page view (folder, filters, loaded pages, scroll) for the
 * lifetime of the tab, so a lost session — which redirects to /login and back —
 * does not dump the user at page 1 of the root folder.
 *
 * Metadata only: no file names, no object ids, no catalogue data. The list is
 * still re-fetched from the server on every restore; this only says *where* to
 * look. `sessionStorage` is per tab and cleared when the tab closes.
 */
export interface FilesViewState {
  folderId: string | null;
  search: string;
  statusFilter: string;
  typeFilter: string;
  minSize: string;
  maxSize: string;
  fromDate: string;
  toDate: string;
  sortField: "created_at" | "display_name" | "size_bytes";
  sortOrder: "asc" | "desc";
  /** Number of 50-object pages that were loaded. */
  pages: number;
  /** Vertical scroll offset, in CSS pixels. */
  scrollY: number;
}

const KEY = "aura-files-view-v1";

const DEFAULT: FilesViewState = {
  folderId: null,
  search: "",
  statusFilter: "",
  typeFilter: "",
  minSize: "",
  maxSize: "",
  fromDate: "",
  toDate: "",
  sortField: "created_at",
  sortOrder: "desc",
  pages: 0,
  scrollY: 0,
};

function isSortField(value: unknown): value is FilesViewState["sortField"] {
  return value === "created_at" || value === "display_name" || value === "size_bytes";
}

/** Read the saved view, or null when there is nothing valid to restore. */
export function loadFilesView(): FilesViewState | null {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<FilesViewState>;
    if (typeof parsed !== "object" || parsed === null) return null;
    return {
      ...DEFAULT,
      ...parsed,
      folderId: typeof parsed.folderId === "string" ? parsed.folderId : null,
      pages: Number.isFinite(parsed.pages) ? Math.max(0, Number(parsed.pages)) : 0,
      scrollY: Number.isFinite(parsed.scrollY)
        ? Math.max(0, Number(parsed.scrollY))
        : 0,
      sortField: isSortField(parsed.sortField) ? parsed.sortField : "created_at",
      sortOrder: parsed.sortOrder === "asc" ? "asc" : "desc",
    };
  } catch {
    return null;
  }
}

/** Merge a partial view into the saved one (filters and scroll update at
 * different rates, so each writer must not erase the other's fields). */
export function patchFilesView(patch: Partial<FilesViewState>): void {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  try {
    const current = loadFilesView() ?? DEFAULT;
    window.sessionStorage.setItem(KEY, JSON.stringify({ ...current, ...patch }));
  } catch {
    // Private windows or a full quota: remembering the view is a convenience.
  }
}

/** Forget the saved view (explicit logout: the next account starts fresh). */
export function clearFilesView(): void {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Ignore: nothing to clear.
  }
}
