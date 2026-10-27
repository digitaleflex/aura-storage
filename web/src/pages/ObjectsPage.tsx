import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useLocation, useNavigate } from "@tanstack/react-router";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ApiError, api, hasAdminAccess, hasScope } from "../lib/api";
import type { FolderItem, ObjectItem, ObjectQuery } from "../lib/api";
import {
  CascadeOp,
  CascadeFailure,
  CascadeScanError,
  CascadeState,
  scanCascade,
  planCascadeOps,
  cascadeOpKey,
} from "../lib/cascade";
import { UploadTray } from "../components/UploadTray";
import { VaultOverview } from "../components/VaultOverview";
import {
  addEntries,
  clearOwner,
  fingerprint,
  pendingEntries,
  removeEntries,
  type JournalEntry,
} from "../lib/uploadJournal";
import type { QueueInput, QueueState } from "../lib/transfer";
import { useTransfers } from "../lib/transferContext";
import {
  loadFilesView,
  patchFilesView,
  type FilesViewState,
} from "../lib/filesViewState";
import {
  MAX_UPLOAD_DEPTH,
  normalizeRelativePath,
  parentDirOf,
  planFolders,
} from "../lib/folderTree";
import { useAuth, useSession } from "../lib/auth";
import { ConfirmAction, Dialog } from "../components/Dialog";
import { makeToast, ToastStack, type Toast } from "../components/Toasts";
import { FolderMark } from "../components/FolderMark";
import { RowMenu } from "../components/RowMenu";
import { describeError } from "../lib/errors";
import { PreviewModal } from "../components/PreviewModal";
import { ShareDialog } from "../components/ShareDialog";
import { PublishDialog } from "../components/PublishDialog";
import { PacksDialog } from "../components/PacksDialog";
import { TagsEditor } from "../components/TagsEditor";
import { ObjectAnalytics } from "../components/ObjectAnalytics";
import {
  MasterModeBanner,
  MasterModeDialog,
  useMasterMode,
} from "../components/MasterMode";
import { isPreviewable } from "../lib/preview";

/** Objects fetched per page ("Charger plus" increments the offset). */
const OBJECTS_PAGE_SIZE = 50;

/**
 * True when a key event belongs to text entry. Global shortcuts must not
 * hijack typing, but they should still work when focus is on a checkbox or a
 * button (e.g. selecting rows then pressing Suppr).
 */
function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target.tagName === "TEXTAREA" || target.tagName === "SELECT") return true;
  if (target.tagName === "INPUT") {
    const type = (target as HTMLInputElement).type;
    return ![
      "checkbox",
      "radio",
      "button",
      "submit",
      "reset",
      "file",
      "range",
      "color",
    ].includes(type);
  }
  return false;
}

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Tous les états" },
  { value: "available", label: "Disponible" },
  { value: "pending", label: "En cours" },
  { value: "verifying", label: "Vérification" },
  { value: "deleted", label: "Corbeille" },
  { value: "expired", label: "Expiré" },
  { value: "failed", label: "Échec" },
  { value: "aborted", label: "Abandonné" },
];

/** Sortable columns: the API field, its label and the order a first click uses. */
const SORT_COLUMNS: {
  field: NonNullable<ObjectQuery["sort"]>;
  label: string;
  firstOrder: NonNullable<ObjectQuery["order"]>;
}[] = [
  { field: "display_name", label: "Nom", firstOrder: "asc" },
  { field: "size_bytes", label: "Taille", firstOrder: "desc" },
  { field: "created_at", label: "Ajouté", firstOrder: "desc" },
];

/** Common media types offered as suggestions; the field stays free text. */
const CONTENT_TYPE_SUGGESTIONS = [
  "application/pdf",
  "application/json",
  "application/octet-stream",
  "image/jpeg",
  "image/png",
  "text/csv",
  "text/plain",
  "audio/mpeg",
  "video/mp4",
];

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) {
    return "taille inconnue";
  }
  if (size === 0) {
    return "0 o";
  }
  const units = ["o", "Ko", "Mo", "Go", "To"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  const value = size / 1024 ** index;
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

/** Seconds -> "m:ss" / "h:mm:ss" for media duration badges. */
function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

const DATE_FORMAT = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** Epoch seconds -> localized label. Invalid/zero values render an em dash. */
function formatDateTime(epoch: number | undefined): string {
  if (epoch === undefined || !Number.isFinite(epoch) || epoch <= 0) {
    return "—";
  }
  return DATE_FORMAT.format(new Date(epoch * 1000));
}

/** "<input type=date>" value -> inclusive epoch-second bound (local day). */
function dateToEpoch(value: string, endOfDay = false): number | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return undefined;
  if (endOfDay) date.setHours(23, 59, 59, 999);
  return Math.floor(date.getTime() / 1000);
}

/** Free-text byte count -> a non-negative integer, or undefined when blank. */
function parseSize(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : undefined;
}

const STATUS_LABELS: Record<string, string> = {
  available: "Disponible",
  pending: "En cours",
  verifying: "Vérification…",
  deleted: "Supprimé",
  purging: "Purge en cours",
  expired: "Expiré",
  failed: "Échec",
  aborted: "Abandonné",
};

/** Friendly type label for scanning; the raw MIME stays in the details panel. */
/** SVG icon for a recognized file type. Returns null for unknown types. */
function FileTypeIcon({ contentType }: { contentType: string }) {
  const value = contentType.toLowerCase();
  if (value.startsWith("image/")) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="8" cy="10" r="2" fill="currentColor" />
        <path d="M3 17l5-4 4 3 5-5 4 4" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    );
  }
  if (value === "application/pdf") {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="6" y="2" width="12" height="20" rx="1" stroke="currentColor" strokeWidth="1.6" />
        <path d="M9 7h6M9 11h6M9 15h4" stroke="currentColor" strokeWidth="1.2" />
      </svg>
    );
  }
  if (value.startsWith("audio/")) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" stroke="currentColor" strokeWidth="1.6" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    );
  }
  if (value.startsWith("video/")) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="2" y="4" width="16" height="16" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M18 9l4-2v10l-4-2" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    );
  }
  if (value === "application/zip" || value === "application/gzip" || value === "application/x-tar") {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="4" y="4" width="16" height="16" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M4 10h16M10 4v6" stroke="currentColor" strokeWidth="1.2" />
      </svg>
    );
  }
  if (value.startsWith("text/")) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" strokeWidth="1.6" />
        <path d="M14 2v6h6M8 13h8M8 17h5" stroke="currentColor" strokeWidth="1.2" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" strokeWidth="1.6" />
      <path d="M14 2v6h6" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

/** Visual family of a file, for the coloured tile in the ledger. */
function fileKind(contentType: string): string {
  const value = contentType.toLowerCase();
  if (value === "application/pdf") return "pdf";
  if (value.startsWith("audio/")) return "audio";
  if (value.startsWith("image/")) return "image";
  if (value.startsWith("video/")) return "video";
  if (value === "application/zip" || value === "application/gzip" || value === "application/x-tar") {
    return "archive";
  }
  if (
    value.includes("wordprocessingml") || value.includes("spreadsheetml") ||
    value.includes("presentationml") || value === "application/msword" ||
    value.startsWith("text/")
  ) {
    return "doc";
  }
  return "other";
}

function typeLabel(contentType: string): string {
  const value = contentType.toLowerCase();
  if (value === "application/pdf") return "PDF";
  if (value.startsWith("image/")) return "Image";
  if (value.startsWith("audio/")) return "Audio";
  if (value.startsWith("video/")) return "Vidéo";
  if (
    value === "application/zip" ||
    value === "application/gzip" ||
    value === "application/x-tar"
  ) {
    return "Archive";
  }
  if (value.includes("wordprocessingml") || value === "application/msword") return "Word";
  if (value.includes("spreadsheetml") || value === "application/vnd.ms-excel") return "Excel";
  if (value.includes("presentationml") || value === "application/vnd.ms-powerpoint") {
    return "PowerPoint";
  }
  if (value === "application/json") return "JSON";
  if (value === "text/csv") return "CSV";
  if (value.startsWith("text/")) return "Texte";
  if (value === "application/octet-stream") return "Binaire";
  return contentType.split("/")[1] ?? contentType;
}

/** Variant class shared by the status badge and the loaded-pages tally, so the
 * two never diverge on colour semantics. */
function statusVariantClass(status: string): string {
  if (status === "available") return "status status-ok";
  if (status === "pending" || status === "verifying") return "status status-warn";
  if (status === "failed") return "status status-error";
  // Deletion stays neutral grey: it never borrows the activity colour.
  if (status === "deleted") return "status status-muted";
  return "status";
}

/** Status shown as a dot plus a word, so it never relies on colour alone. */
function StatusLabel({ status }: { status: string }) {
  return <span className={statusVariantClass(status)}>{STATUS_LABELS[status] ?? status}</span>;
}

/** Commit phase durations, in whole milliseconds, French number grouping. */
/** Server-side soft delete accepts only `available` or `pending` rows; anything
 * else is refused with 409. The bulk selection and the per-row "Supprimer"
 * action share this predicate so they never diverge. */
function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** In the trash and fully uploaded: the server refuses to restore anything else. */
function isRestorable(item: ObjectItem): boolean {
  return item.status === "deleted" && item.size_bytes >= 0;
}

function isDeletable(item: ObjectItem): boolean {
  return item.status === "available" || item.status === "pending";
}


/** The whole folder tree is fetched in one request (`?all=true`); the hierarchy
 * is rebuilt client-side from parent_id for breadcrumbs and the move pickers. */
export function ObjectsPage() {
  const { csrf } = useAuth();
  const session = useSession();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  // The live queue is owned by the shell (TransfersProvider): imports keep
  // running when the user opens the transfers page, and the same snapshot
  // feeds the floating tray and the transfers page.
  const transfers = useTransfers();
  const queue = transfers.queue;

  // The folder, filters and position the user had before a lost session. Read
  // once: after this render the component owns the state and writes it back.
  const [restoredView] = useState<FilesViewState | null>(() => loadFilesView());
  const [viewMode, setViewMode] = useState<"list" | "grid">(
    () => restoredView?.viewMode ?? "list",
  );

  const [currentFolderId, setCurrentFolderId] = useState<string | null>(
    () => restoredView?.folderId ?? null,
  );
  // Uploads run through the M03 transfer engine as a bounded multi-file queue.
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [pendingFolderEntries, setPendingFolderEntries] = useState<{ file: File; rel: string }[]>([]);
  const dirInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // A refused (409, non-empty) folder deletion is actionable: keep the target
  // so the user can empty it and retry, instead of losing the failure.
  const [folderDeleteError, setFolderDeleteError] = useState<{
    id: string;
    name: string;
  } | null>(null);
  // Recursive folder deletion: opened from the 409 refusal or from the
  // "Supprimer avec son contenu" option; always explicit and confirmed.
  const [folderDeleteWithContent, setFolderDeleteWithContent] = useState(false);
  const [cascade, setCascade] = useState<CascadeState | null>(null);
  const [cascadeConfirmText, setCascadeConfirmText] = useState("");
  // Mirror of the live cascade state, read/written by the async run loop where
  // a state updater would otherwise close over a stale render.
  const cascadeRef = useRef<CascadeState | null>(null);
  const cascadeCancelRef = useRef(false);
  const cascadeDialogRef = useRef<HTMLDialogElement | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  /** Badges de statut : répartition des fichiers de la file par phase. */
  const phaseBadges = useMemo(() => {
    let paused = 0;
    let idle = 0;
    let uploading = 0;
    let validating = 0;
    let available = 0;
    let failed = 0;
    let cancelled = 0;
    for (const item of queue.items) {
      if (item.paused) paused += 1;
      switch (item.state.phase) {
        case "requesting-intent":
        case "uploading":
          uploading += 1;
          break;
        case "validating":
          validating += 1;
          break;
        case "available":
          available += 1;
          break;
        case "failed":
          failed += 1;
          break;
        case "cancelled":
          cancelled += 1;
          break;
        default:
          idle += 1;
      }
    }
    const entries = [
      { key: "paused", label: "Suspendu", count: paused, tone: "warn" },
      { key: "failed", label: "Échec", count: failed, tone: "error" },
      { key: "validating", label: "Vérification", count: validating, tone: "run" },
      { key: "uploading", label: "Envoi", count: uploading, tone: "run" },
      { key: "idle", label: "En attente", count: idle, tone: "muted" },
      { key: "available", label: "Prêt", count: available, tone: "ok" },
      { key: "cancelled", label: "Annulé", count: cancelled, tone: "muted" },
    ];
    return entries.filter((entry) => entry.count > 0);
  }, [queue.items]);

  function dismissToast(id: number) {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }

  function notify(kind: Toast["kind"], text: string, action?: Toast["action"]) {
    setToasts((current) => [...current.slice(-4), makeToast(kind, text, action)]);
  }
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [renameTarget, setRenameTarget] = useState<FolderItem | null>(null);
  const [renameName, setRenameName] = useState("");
  const [moveTarget, setMoveTarget] = useState<FolderItem | null>(null);
  const [moveObjectTarget, setMoveObjectTarget] = useState<ObjectItem | null>(null);
  const [details, setDetails] = useState<ObjectItem | null>(null);
  const [previewTarget, setPreviewTarget] = useState<ObjectItem | null>(null);
  const [shareTarget, setShareTarget] = useState<ObjectItem | null>(null);
  const [publishTarget, setPublishTarget] = useState<ObjectItem | null>(null);
  const [packsOpen, setPacksOpen] = useState(false);
  const [tagFilter, setTagFilter] = useState("");
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // The import panel opens on demand (header button) and stays open while it
  // holds pending files, a queue or an error; a drop anywhere also opens it.
  const [intakeOpen, setIntakeOpen] = useState(false);
  // Arriving from the transfers page's "Ajouter des fichiers": open the
  // existing import panel once, then drop the one-shot query parameter.
  useEffect(() => {
    const search = location.search as { import?: string };
    if (search.import !== "1") return;
    setIntakeOpen(true);
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(() => {
      document
        .getElementById("intake")
        ?.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
    });
    void navigate({
      to: "/",
      search: (prev) => {
        const next = { ...(prev as { import?: string }) };
        next.import = undefined;
        return next;
      },
      replace: true,
    });
  }, [location.search, navigate]);
  // Directory import: which folder of the plan is being created (item P1.7).
  const [folderProgress, setFolderProgress] = useState<{
    done: number;
    total: number;
    name: string;
  } | null>(null);
  // Folder drops can take a while (tree walk + folder creation). This drives a
  // persistent "patientez" status so the drop never looks dead before the queue
  // tray appears.
  const [dropScan, setDropScan] = useState<{ files: number } | null>(null);
  // Bulk delete: the dialog stays open while the per-file loop reports its
  // real progress instead of a silent "Suppression…" (item P1.8).
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [deleteManyProgress, setDeleteManyProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  // Stable callbacks for the memoised <UploadTray>: inline arrows would change
  // on every render and defeat the memo.
  const clearTray = useCallback(() => transfers.clear(), [transfers.clear]);
  const pauseQueue = useCallback(() => transfers.pauseAll(), [transfers.pauseAll]);
  const resumeQueue = useCallback(() => transfers.resumeAll(), [transfers.resumeAll]);
  const cancelQueueItem = useCallback(
    (id: string) => transfers.cancelItem(id),
    [transfers.cancelItem],
  );
  const retryQueueItem = useCallback(
    (id: string) => {
      setUploadError(null);
      transfers.retryItem(id);
    },
    [transfers.retryItem],
  );
  const libraryRefreshRef = useRef({ at: 0, done: 0 });

  // File d'attente automatique : placeholder (defini plus bas apres transferActive)

  // Infinite scroll : charger automatiquement quand le bouton "Charger plus" est visible
  // (defini apres objectsQuery pour eviter le TDZ)
  const [pendingConfirm, setPendingConfirm] = useState<{
    title: string;
    message: ReactNode;
    confirmLabel: string;
    danger?: boolean;
    /** Folder deletion: offer the "with its content" recursive option. */
    folderCascade?: boolean;
    /** `withContent` is only meaningful for a folder deletion confirmation. */
    onConfirm: (withContent: boolean) => void;
  } | null>(null);

  // -- search / filter / sort (server-side; M02) ---------------------------
  const [search, setSearch] = useState(() => restoredView?.search ?? "");
  const [debouncedSearch, setDebouncedSearch] = useState(
    () => restoredView?.search ?? "",
  );
  const [statusFilter, setStatusFilter] = useState(
    () => restoredView?.statusFilter ?? "",
  );
  const [typeFilter, setTypeFilter] = useState(
    () => restoredView?.typeFilter ?? "",
  );
  const [minSize, setMinSize] = useState(() => restoredView?.minSize ?? "");
  const [maxSize, setMaxSize] = useState(() => restoredView?.maxSize ?? "");
  const [fromDate, setFromDate] = useState(() => restoredView?.fromDate ?? "");
  const [toDate, setToDate] = useState(() => restoredView?.toDate ?? "");
  const [sortField, setSortField] = useState<NonNullable<ObjectQuery["sort"]>>(
    () => restoredView?.sortField ?? "created_at",
  );
  const [sortOrder, setSortOrder] = useState<NonNullable<ObjectQuery["order"]>>(
    () => restoredView?.sortOrder ?? "desc",
  );

  // Debounce the name filter so typing does not fire one request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const filters = useMemo<ObjectQuery>(() => {
    const query: ObjectQuery = { folderId: currentFolderId };
    if (debouncedSearch) query.q = debouncedSearch;
    if (statusFilter) query.status = statusFilter;
    if (typeFilter.trim()) query.contentType = typeFilter.trim();
    const min = parseSize(minSize);
    const max = parseSize(maxSize);
    if (min !== undefined) query.minSize = min;
    if (max !== undefined) query.maxSize = max;
    const after = dateToEpoch(fromDate);
    const before = dateToEpoch(toDate, true);
    if (after !== undefined) query.createdAfter = after;
    if (before !== undefined) query.createdBefore = before;
    if (tagFilter.trim()) query.tag = tagFilter.trim().toLowerCase();
    query.sort = sortField;
    query.order = sortOrder;
    return query;
  }, [
    currentFolderId,
    debouncedSearch,
    statusFilter,
    typeFilter,
    minSize,
    maxSize,
    fromDate,
    toDate,
    sortField,
    sortOrder,
    tagFilter,
  ]);

  const hasActiveFilters =
    debouncedSearch !== "" ||
    statusFilter !== "" ||
    typeFilter.trim() !== "" ||
    minSize.trim() !== "" ||
    maxSize.trim() !== "" ||
    fromDate !== "" ||
    toDate !== "";

  /** Advanced filters moved off the default screen; the count badges the toggle. */
  const advancedCount = [typeFilter, minSize, maxSize, fromDate, toDate].filter(
    (value) => value.trim() !== "",
  ).length;

  function resetFilters() {
    setSearch("");
    setStatusFilter("");
    setTypeFilter("");
    setMinSize("");
    setMaxSize("");
    setFromDate("");
    setToDate("");
    setTagFilter("");
  }

  const canPurge = hasScope(session.data?.scopes, "objects:purge");

  // Permissions d'écriture : tout utilisateur authentifié peut créer des dossiers
  // et importer des fichiers ; l'API reste autoritaire.
  const canCreate = !!session.data?.id;
  const canCreateFolder = !!session.data?.id;
  // Recursive deletion deletes objects (objects:delete) inside folders the
  // caller owns (objects:write); it is a human-only flow, like folders. When
  // either scope is missing the option is never offered.
  const canCascadeDelete =
    session.data?.kind === "user" &&
    hasScope(session.data?.scopes, "objects:delete") &&
    hasScope(session.data?.scopes, "objects:write");
  // Minting and revoking public links is human-only server-side (a leaked
  // machine token must not create links that outlive its revocation).
  const canShare =
    session.data?.kind === "user" && hasScope(session.data?.scopes, "objects:read");

  // Storage usage is only ever the real admin figure (`GET /admin/usage`,
  // `admin:read`): no fabricated capacity is displayed for anyone else.
  const usageQuery = useQuery({
    queryKey: ["admin", "usage"],
    queryFn: () => api.adminUsage(),
    enabled: hasAdminAccess(session.data?.role),
    retry: false,
  });

  /** True while any file of the queue is transferring (blocks double submit). */
  const transferActive = queue.active > 0;

  // File d'attente automatique : quand le transfert se termine et qu'il y a
  // des fichiers/dossiers en attente, les lancer automatiquement.
  useEffect(() => {
    if (transferActive) return;
    if (pendingFiles.length === 0 && pendingFolderEntries.length === 0) return;
    if (!csrf) return;
    // Petite temporisation pour laisser l'UI se stabiliser
    const timer = setTimeout(() => {
      if (pendingFolderEntries.length > 0) {
        const folderList = pendingFolderEntries.map((entry) => entry.file);
        const folderRels = pendingFolderEntries.map((entry) => entry.rel);
        const looseList = pendingFiles;
        const looseRels = pendingFiles.map((file) => file.name);
        void uploadRelPaths([...folderList, ...looseList], [...folderRels, ...looseRels]);
        setPendingFiles([]);
        setPendingFolderEntries([]);
      } else {
        launchQueue(
          csrf,
          pendingFiles.map((file) => ({ file, rel: file.name, folderId: currentFolderId })),
        );
        setPendingFiles([]);
      }
      setNotice(null);
    }, 500);
    return () => clearTimeout(timer);
  }, [transferActive, pendingFiles.length, pendingFolderEntries.length, csrf, currentFolderId]);

  // -- Upload journal: resume a long import after a reload --------------------
  const owner = session.data?.id ?? null;
  const [resumable, setResumable] = useState<JournalEntry[]>([]);
  const resumeFilesRef = useRef<HTMLInputElement>(null);
  const resumeDirRef = useRef<HTMLInputElement>(null);
  /** Journal keys already forgotten, so each settled file is removed once. */
  const forgottenRef = useRef<Set<string>>(new Set());

  function refreshResumable() {
    if (!owner) return;
    void pendingEntries(owner).then(setResumable);
  }

  useEffect(() => {
    if (!transferActive) refreshResumable();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [owner, transferActive]);

  // Leaving the page mid-import loses the files in flight: ask first.
  useEffect(() => {
    if (!transferActive) return;
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [transferActive]);

  // Raccourcis clavier : / pour focus recherche
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (isTextEntryTarget(event.target)) return;
      // Un "/" majuscule ouvre la légende, pas la recherche : les deux
      // raccourcis partagent la même touche physique.
      if (event.key === "/" && !event.shiftKey) {
        event.preventDefault();
        const searchInput = document.querySelector('input[name="filter"]') as HTMLInputElement;
        if (searchInput) searchInput.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Coller-pour-importer (Ctrl+V / Cmd+V)
  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const files = event.clipboardData?.files;
      if (!files || files.length === 0) return;
      // Ignorer si on est dans un champ de saisie
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
      event.preventDefault();
      setPendingFiles((prev) => [...prev, ...Array.from(files)]);
      setIntakeOpen(true);
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  // Keep the screen (and so the machine) awake while files are being sent.
  // Best effort: unsupported browsers or a refused lock change nothing.
  useEffect(() => {
    if (!transferActive) return;
    let lock: { release(): Promise<void> } | null = null;
    let released = false;
    const wakeLock = (navigator as Navigator & {
      wakeLock?: { request(type: "screen"): Promise<{ release(): Promise<void> }> };
    }).wakeLock;
    wakeLock
      ?.request("screen")
      .then((acquired) => {
        if (released) void acquired.release();
        else lock = acquired;
      })
      .catch(() => undefined);
    return () => {
      released = true;
      void lock?.release().catch(() => undefined);
    };
  }, [transferActive]);

  /** Start a queue, journaling every file so the import survives a reload. */
  function launchQueue(
    activeCsrf: string,
    entries: Array<{
      file: File;
      rel: string;
      folderId: string | null;
      idempotencyKey?: string;
    }>,
  ) {
    const journal: JournalEntry[] = [];
    const inputs: QueueInput[] = entries.map(({ file, rel, folderId, idempotencyKey }) => {
      if (!owner) return { file, folderId };
      const key = fingerprint(owner, rel, file);
      // One key per file for its whole life: a resume after a reload reopens
      // the same server session and keeps the parts already sent.
      const idem = idempotencyKey ?? newIdempotencyKey();
      forgottenRef.current.delete(key);
      journal.push({ key, owner, rel, size: file.size, folderId, idempotencyKey: idem });
      return { file, folderId, key, idempotencyKey: idem };
    });
    void addEntries(journal);
    libraryRefreshRef.current = { at: Date.now(), done: 0 };
    transfers.start(inputs, {
      csrf: activeCsrf,
      folderId: currentFolderId,
      onUpdate: handleQueueUpdate,
      // A file whose PUT died with the link is replayed by the queue as soon as
      // the browser reports the network back: say so, instead of leaving the
      // user in front of a tray full of "Échec" they did not ask to fix.
      onAutoRetry: (count) =>
        notify(
          "ok",
          `Connexion rétablie : ${count} fichier${count > 1 ? "s" : ""} relancé${
            count > 1 ? "s" : ""
          } automatiquement.`,
        ),
    });
  }

  /** Re-selected files: send only those the journal still lists. */
  function handleResume(selected: FileList | null) {
    if (!selected || selected.length === 0 || !owner || !csrf || transferActive) return;
    const byKey = new Map(resumable.map((entry) => [entry.key, entry]));
    // Same file picked through the other picker (plain files vs folder) has a
    // different relative path: fall back to name + size + mtime.
    const byName = new Map(
      resumable.map((entry) => [
        `${entry.rel.split("/").pop()}\u0000${entry.size}`,
        entry,
      ]),
    );
    const matched: Array<{
      file: File;
      rel: string;
      folderId: string | null;
      idempotencyKey?: string;
    }> = [];
    const seen = new Set<string>();
    for (const file of Array.from(selected)) {
      const rel = normalizeRelativePath(
        (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
      );
      const entry =
        byKey.get(fingerprint(owner, rel, file)) ??
        (() => {
          const candidate = byName.get(`${file.name}\u0000${file.size}`);
          return candidate &&
            candidate.key === fingerprint(owner, candidate.rel, file)
            ? candidate
            : undefined;
        })();
      if (!entry || seen.has(entry.key)) continue;
      seen.add(entry.key);
      matched.push({
        file,
        rel: entry.rel,
        folderId: entry.folderId,
        idempotencyKey: entry.idempotencyKey,
      });
    }
    const ignored = selected.length - matched.length;
    if (matched.length === 0) {
      setUploadError(
        "Aucun des fichiers choisis ne correspond à l'import interrompu (même nom, taille et date de modification).",
      );
      return;
    }
    setUploadError(null);
    setNotice(
      `Reprise de ${matched.length} fichier(s)` +
        (ignored > 0 ? ` ; ${ignored} déjà envoyé(s) ou hors import ignoré(s).` : "."),
    );
    launchQueue(csrf, matched);
  }

  function forgetResumable() {
    if (!owner) return;
    void clearOwner(owner).then(() => setResumable([]));
  }

  const treeQuery = useQuery({
    queryKey: ["folders", "all"],
    queryFn: () => api.listAllFolders(),
  });
  const objectsQuery = useInfiniteQuery({
    queryKey: ["objects", filters],
    queryFn: ({ pageParam }) =>
      api.listObjects({ ...filters, limit: OBJECTS_PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, _pages, lastOffset) =>
      lastPage.items.length === OBJECTS_PAGE_SIZE
        ? lastOffset + lastPage.items.length
        : undefined,
  });

  // Infinite scroll : charger automatiquement quand le bouton "Charger plus" est visible
  useEffect(() => {
    if (!objectsQuery.hasNextPage) return;
    const el = loadMoreRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !objectsQuery.isFetchingNextPage) {
          void objectsQuery.fetchNextPage();
        }
      },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [objectsQuery.hasNextPage, objectsQuery.isFetchingNextPage]);

  // -- restore the view after a lost session -------------------------------
  // The guard sends the user to /login?redirect=… and the login page comes
  // back here, but the in-memory list is gone. sessionStorage keeps the
  // folder, filters, page depth and scroll offset; the catalogue is still
  // re-fetched from the server (no object data is stored client-side).
  const restorePagesRef = useRef(restoredView?.pages ?? 0);
  const restoreScrollRef = useRef(restoredView?.scrollY ?? 0);
  const restoreDoneRef = useRef(
    !restoredView || (restoredView.pages <= 1 && restoredView.scrollY <= 0),
  );
  const initialFiltersRef = useRef(filters);

  // A filter/folder change is a new view: never force the old depth onto it.
  useEffect(() => {
    if (filters !== initialFiltersRef.current) {
      initialFiltersRef.current = filters;
      restoreDoneRef.current = true;
    }
  }, [filters]);

  // Filters and folder change slowly: one write per keystroke burst.
  useEffect(() => {
    const timer = setTimeout(() => {
      patchFilesView({
        folderId: currentFolderId,
        search,
        statusFilter,
        typeFilter,
        minSize,
        maxSize,
        fromDate,
        toDate,
        sortField,
        sortOrder,
        viewMode,
      });
    }, 200);
    return () => clearTimeout(timer);
  }, [
    currentFolderId,
    search,
    statusFilter,
    typeFilter,
    minSize,
    maxSize,
    fromDate,
    toDate,
    sortField,
    sortOrder,
    viewMode,
  ]);

  // Scroll offset and page depth are written together: a scroll position is
  // only reachable if the pages that produced it are loaded again.
  useEffect(() => {
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        patchFilesView({
          scrollY: window.scrollY,
          pages: objectsQuery.data?.pages.length ?? 0,
        });
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [objectsQuery.data?.pages.length]);

  // Re-load the missing pages sequentially, then put the viewport back. The
  // auto-load observer is idle until the list is tall enough, so this is what
  // actually reconstructs a 200+ object view.
  useEffect(() => {
    if (restoreDoneRef.current) return;
    if (!objectsQuery.isSuccess) return;
    const loaded = objectsQuery.data.pages.length;
    if (loaded < restorePagesRef.current && objectsQuery.hasNextPage) {
      if (!objectsQuery.isFetchingNextPage) void objectsQuery.fetchNextPage();
      return;
    }
    restoreDoneRef.current = true;
    const y = restoreScrollRef.current;
    if (y > 0) {
      window.requestAnimationFrame(() => window.scrollTo({ top: y, left: 0 }));
    }
  }, [
    objectsQuery.isSuccess,
    objectsQuery.data,
    objectsQuery.hasNextPage,
    objectsQuery.isFetchingNextPage,
  ]);

  const tree = treeQuery.data?.items ?? [];
  const byId = useMemo(() => new Map(tree.map((f) => [f.id, f])), [tree]);
  // A restored folder may have been deleted while the session was away.
  useEffect(() => {
    if (!treeQuery.isSuccess) return;
    if (currentFolderId && !byId.has(currentFolderId)) {
      setCurrentFolderId(null);
    }
  }, [treeQuery.isSuccess, byId, currentFolderId]);
  const childrenOf = useMemo(() => {
    const map = new Map<string | null, FolderItem[]>();
    for (const folder of tree) {
      const key = folder.parent_id;
      const bucket = map.get(key);
      if (bucket) {
        bucket.push(folder);
      } else {
        map.set(key, [folder]);
      }
    }
    return map;
  }, [tree]);

  const subfolders = childrenOf.get(currentFolderId) ?? [];

  const breadcrumb = useMemo(() => {
    const path: FolderItem[] = [];
    let cursor = currentFolderId;
    let guard = 0;
    while (cursor && guard < 64) {
      const folder = byId.get(cursor);
      if (!folder) break;
      path.unshift(folder);
      cursor = folder.parent_id;
      guard += 1;
    }
    return path;
  }, [byId, currentFolderId]);

  /** Human-readable folder path for an object ("Racine / Dossier / Sous-dossier"). */
  function folderPath(folderId: string | null): string {
    if (!folderId) return "Racine";
    const names: string[] = [];
    let cursor: string | null = folderId;
    let guard = 0;
    while (cursor && guard < 64) {
      const folder: FolderItem | undefined = byId.get(cursor);
      if (!folder) break;
      names.unshift(folder.name);
      cursor = folder.parent_id;
      guard += 1;
    }
    return ["Racine", ...names].join(" / ");
  }

  function invalidateLibrary() {
    void queryClient.invalidateQueries({ queryKey: ["objects"] });
    void queryClient.invalidateQueries({ queryKey: ["folders"] });
  }

  function reportError(err: unknown, fallback: string) {
    setNotice(null);
    setActionError(describeError(err, fallback));
  }

  // -- mutations -----------------------------------------------------------
  const createFolderMutation = useMutation({
    mutationFn: (name: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.createFolder({ name, parent_id: currentFolderId }, csrf);
    },
    onSuccess: () => {
      setNewFolderOpen(false);
      setNewFolderName("");
      setNotice("Dossier créé.");
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Création du dossier impossible."),
  });

  const renameMutation = useMutation({
    mutationFn: (input: { id: string; name: string }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.updateFolder(input.id, { name: input.name }, csrf);
    },
    onSuccess: () => {
      setRenameTarget(null);
      setNotice("Dossier renommé.");
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Renommage impossible."),
  });

  const moveMutation = useMutation({
    mutationFn: (input: { id: string; parentId: string | null }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.updateFolder(input.id, { parent_id: input.parentId }, csrf);
    },
    onSuccess: () => {
      setMoveTarget(null);
      setNotice("Dossier déplacé.");
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Déplacement impossible."),
  });

  const moveObjectMutation = useMutation({
    mutationFn: (input: { id: string; folderId: string | null }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.moveObject(input.id, input.folderId, csrf);
    },
    onSuccess: () => {
      setMoveObjectTarget(null);
      setDetails(null);
      setNotice("Objet déplacé.");
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Déplacement de l'objet impossible."),
  });

  // Folder delete is confirmed against the server: a non-empty folder (409) is
  // surfaced as an actionable refusal (friendly FR + retry), never a fake success.
  const deleteFolderMutation = useMutation({
    mutationFn: (input: { id: string; name: string }) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.deleteFolder(input.id, csrf);
    },
    onSuccess: (_data, input) => {
      if (currentFolderId === input.id) setCurrentFolderId(null);
      setFolderDeleteError(null);
      setNotice("Dossier supprimé.");
      invalidateLibrary();
    },
    onError: (err, input) => {
      setNotice(null);
      if (err instanceof ApiError && err.status === 409) {
        // The server refuses a folder that still holds files or subfolders.
        setActionError(null);
        setFolderDeleteError({ id: input.id, name: input.name });
        return;
      }
      setFolderDeleteError(null);
      reportError(err, "Suppression du dossier impossible.");
    },
  });

  // Delete is confirmed against the server: the row is only refreshed (never
  // removed locally) once the API reports success.
  const deleteObjectMutation = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.deleteObject(id, csrf);
    },
    onSuccess: (_data, id) => {
      setDetails(null);
      notify("ok", "Objet marqué comme supprimé. Les octets restent jusqu'à une purge.", {
        label: "Annuler",
        onClick: () => restoreMutation.mutate(id),
      });
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Suppression impossible."),
  });

  // Bulk delete reuses the audited single-object endpoint once per selected
  // file (no bulk API surface): sequential, per-file outcome, server truth.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const deleteManyMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      if (!csrf) throw new Error("Session expirée.");
      const failed: string[] = [];
      let deleted = 0;
      setDeleteManyProgress({ done: 0, total: ids.length });
      for (const id of ids) {
        try {
          await api.deleteObject(id, csrf);
          deleted += 1;
        } catch {
          const target = items.find((item) => item.id === id);
          failed.push(target?.display_name ?? id);
        } finally {
          setDeleteManyProgress({ done: deleted + failed.length, total: ids.length });
        }
      }
      return { deleted, failed };
    },
    onSuccess: ({ deleted, failed }, ids) => {
      setBulkDeleteOpen(false);
      setDeleteManyProgress(null);
      setSelectedIds(new Set());
      setDetails(null);
      if (failed.length === 0) {
        notify(
          "ok",
          deleted === 1
            ? "1 objet marqué comme supprimé. Les octets restent jusqu'à une purge."
            : `${deleted} objets marqués comme supprimés. Les octets restent jusqu'à une purge.`,
          {
            label: "Annuler",
            onClick: () => {
              if (!csrf) return;
              for (const id of ids) {
                void restoreMutation.mutate(id);
              }
            },
          },
        );
      } else {
        const deletedLabel = deleted === 1 ? "1 supprimé" : `${deleted} supprimés`;
        const failedLabel =
          failed.length === 1 ? "1 échec" : `${failed.length} échecs`;
        notify(
          "error",
          `${deletedLabel}, ${failedLabel} : ${failed.slice(0, 5).join(", ")}${failed.length > 5 ? "…" : ""}`,
        );
      }
      invalidateLibrary();
    },
    onError: (err) => {
      setBulkDeleteOpen(false);
      setDeleteManyProgress(null);
      reportError(err, "Suppression en masse impossible.");
    },
  });

  // Raccourcis clavier globaux (P1.1): `?` ouvre la légende et `Suppr`
  // prépare la suppression de la sélection. Ignorés dans les champs de
  // saisie et quand un dialogue est ouvert (il a déjà son propre clavier).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (isTextEntryTarget(event.target)) return;
      if (document.querySelector("dialog[open]")) return;
      if (event.key === "?" || (event.key === "/" && event.shiftKey)) {
        // "? peut arriver tel quel (clavier réel) ou comme "/" + Shift
        // (événement synthétique, claviers où ? exige une autre touche).
        event.preventDefault();
        setShortcutsOpen(true);
        return;
      }
      if (
        event.key === "Delete" &&
        selectedIds.size > 0 &&
        !deleteManyMutation.isPending
      ) {
        event.preventDefault();
        setBulkDeleteOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedIds.size, deleteManyMutation.isPending]);

  const restoreMutation = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.restoreObject(id, csrf);
    },
    onSuccess: () => {
      setDetails(null);
      notify("ok", "Fichier restauré depuis la corbeille.");
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Restauration impossible."),
  });

  // -- Master mode: bulk purges without a confirmation per item ------------
  const master = useMasterMode();
  const [masterDialogOpen, setMasterDialogOpen] = useState(false);
  const bulkPurgeMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.bulkPurge(ids, csrf);
    },
    onSuccess: (out) => {
      setSelectedIds(new Set());
      setDetails(null);
      notify(
        out.failed.length ? "error" : "ok",
        `${out.purged.length} fichier(s) purgé(s) définitivement` +
          (out.failed.length
            ? ` ; ${out.failed.length} échec(s) du stockage, fiches conservées.`
            : "."),
      );
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Purge en masse impossible."),
  });
  const emptyTrashMutation = useMutation({
    mutationFn: async () => {
      if (!csrf) throw new Error("Session expirée.");
      let purged = 0;
      let failed = 0;
      // The server purges at most one batch per call and says when to go on.
      for (let round = 0; round < 50; round += 1) {
        const out = await api.emptyTrash(csrf);
        purged += out.purged.length;
        failed += out.failed.length;
        if (!out.more || out.purged.length === 0) break;
      }
      return { purged, failed };
    },
    onSuccess: ({ purged, failed }) => {
      notify(
        failed ? "error" : "ok",
        purged === 0
          ? "La corbeille était déjà vide."
          : `Corbeille vidée : ${purged} fichier(s) purgé(s)` +
              (failed ? ` ; ${failed} échec(s) du stockage, fiches conservées.` : "."),
      );
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Vidage de la corbeille impossible."),
  });

  const purgeMutation = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.purgeObject(id, csrf);
    },
    onSuccess: () => {
      setDetails(null);
      setNotice("Objet purgé définitivement.");
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Purge impossible."),
  });

  // Abandon a stuck pending upload intent: the backend deletes the partial
  // bytes and the row leaves the "En cours" state. Re-uploading the same
  // file afterwards mints a fresh intent.
  const abortUploadMutation = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.abortObject(id, csrf);
    },
    onSuccess: () => {
      setDetails(null);
      setNotice("Envoi abandonné, octets partiels supprimés.");
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Abandon impossible."),
  });

  // -- handlers ------------------------------------------------------------
  /** Shared queue subscriber: mirrors state and reacts when it settles. */
  function handleQueueUpdate(next: QueueState) {
    const nowMs = Date.now();
    // Files become visible as they are verified, not only when the whole batch
    // ends (an import can run for hours): refresh the ledger at most every 10 s.
    const refresh = libraryRefreshRef.current;
    if (!next.finished && next.done > refresh.done && nowMs - refresh.at >= 10_000) {
      libraryRefreshRef.current = { at: nowMs, done: next.done };
      invalidateLibrary();
    }
    // Confirmed by the server, or cancelled on purpose: nothing left to resume.
    const settled = next.items
      .filter(
        (item) =>
          item.key !== undefined &&
          (item.state.phase === "available" || item.state.phase === "cancelled") &&
          !forgottenRef.current.has(item.key),
      )
      .map((item) => item.key as string);
    if (settled.length > 0) {
      for (const key of settled) forgottenRef.current.add(key);
      void removeEntries(settled);
    }
    if (!next.finished) return;
    if (next.done > 0) {
      invalidateLibrary();
      notify("ok", `${next.done} fichier(s) vérifié(s) et disponible(s).`, {
        label: "Voir",
        onClick: () => void navigate({ to: "/transfers" }),
      });
    }
    if (next.failed > 0) {
      const firstFailed = next.items.find((item) => item.state.phase === "failed");
      setUploadError(firstFailed?.state.error ?? "Envoi impossible.");
    } else {
      setUploadError(null);
    }
  }

  function handleUpload(event: FormEvent) {
    event.preventDefault();
    setUploadError(null);
    setNotice(null);
    if (pendingFiles.length === 0 && pendingFolderEntries.length === 0) {
      setUploadError("Choisissez au moins un fichier ou un dossier.");
      return;
    }
    if (transferActive) {
      // File d'attente : les fichiers sont mis en attente et seront uploadés
      // automatiquement quand le transfert en cours se termine.
      if (pendingFiles.length > 0) {
        setNotice(
          `${pendingFiles.length} fichier(s) mis en file d'attente — ils seront uploadés automatiquement à la fin du transfert en cours.`,
        );
      }
      if (pendingFolderEntries.length > 0) {
        setNotice("Dossiers en attente — ils seront importés à la fin du transfert en cours.");
      }
      return;
    }
    if (!csrf) {
      setUploadError("Session expirée. Reconnectez-vous.");
      return;
    }
    // Garde-fou taille client : vérifier max_object_bytes avant l'upload
    const maxBytes = usageQuery.data?.limits?.max_object_bytes;
    const combinedForSize = [
      ...pendingFiles,
      ...pendingFolderEntries.map((e) => e.file),
    ];
    if (maxBytes && maxBytes > 0) {
      const oversized = combinedForSize.filter((f) => f.size > maxBytes);
      if (oversized.length > 0) {
        const names = oversized.map((f) => f.name).join(", ");
        setUploadError(
          `Fichier(s) trop volumineux (max ${formatBytes(maxBytes)}) : ${names}. ` +
            "Réduisez la taille ou contactez l'administrateur.",
        );
        return;
      }
    }
    if (pendingFolderEntries.length > 0) {
      const folderList = pendingFolderEntries.map((e) => e.file);
      const folderRels = pendingFolderEntries.map((e) => e.rel);
      const looseList = pendingFiles;
      const looseRels = pendingFiles.map((f) => f.name);
      void uploadRelPaths([...folderList, ...looseList], [...folderRels, ...looseRels]);
      setPendingFiles([]);
      setPendingFolderEntries([]);
      return;
    }
    launchQueue(
      csrf,
      pendingFiles.map((file) => ({ file, rel: file.name, folderId: currentFolderId })),
    );
    // The queue now owns the submitted files: clear them so anything dropped
    // during the transfer stays visible as a real backlog for the next run.
    setPendingFiles([]);
  }

  /** Directory import (#64): recreate the missing folders, then upload in place. */
  async function handleFolderUpload(selected: FileList | null) {
    if (!selected || selected.length === 0) return;
    const list = Array.from(selected);
    const relPaths = list.map((file) =>
      normalizeRelativePath(
        (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
      ),
    );
    setUploadError(null);
    setPendingFolderEntries((current) => [
      ...current,
      ...list.map((file, index) => ({ file, rel: relPaths[index] ?? file.name })),
    ]);
  }

  /** Shared core: plan folders, create them, queue files with folder ids. */
  async function uploadRelPaths(list: File[], relPaths: string[]) {
    if (!csrf) {
      setUploadError("Session expirée. Reconnectez-vous.");
      return;
    }
    if (transferActive) return;
    setUploadError(null);
    setNotice(null);

    const plan = planFolders(relPaths);
    const tooDeep = new Set(plan.tooDeep);
    const kept = list
      .map((file, index) => ({ file, rel: relPaths[index] ?? file.name }))
      .filter((item) => !tooDeep.has(item.rel));
    if (kept.length === 0) {
      setUploadError("Aucun fichier importable dans cette sélection.");
      return;
    }

    const keyOf = (parentId: string | null, name: string) =>
      `${parentId ?? "root"}/${name}`;
    const folderIds = new Map<string, string>(); // relative path -> id
    const existing = new Map<string, string>(); // parentId/name -> id
    for (const folder of tree) {
      existing.set(keyOf(folder.parent_id, folder.name), folder.id);
    }

    if (plan.folders.length > 0) {
      setFolderProgress({
        done: 0,
        total: plan.folders.length,
        name: plan.folders[0]!.name,
      });
    }

    let createdAny = false;
    for (const [index, folder] of plan.folders.entries()) {
      setFolderProgress({
        done: index,
        total: plan.folders.length,
        name: folder.name,
      });
      const parentId = folder.parentPath
        ? (folderIds.get(folder.parentPath) ?? currentFolderId)
        : currentFolderId;
      const key = keyOf(parentId, folder.name);
      const known = existing.get(key);
      if (known) {
        folderIds.set(folder.path, known);
        continue;
      }
      try {
        const made = await api.createFolder(
          { name: folder.name, parent_id: parentId },
          csrf,
        );
        existing.set(key, made.id);
        folderIds.set(folder.path, made.id);
        createdAny = true;
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          try {
            const all = await api.listAllFolders();
            const found = all.items.find(
              (candidate) =>
                (candidate.parent_id ?? null) === (parentId ?? null) &&
                candidate.name === folder.name,
            );
            if (found) {
              existing.set(key, found.id);
              folderIds.set(folder.path, found.id);
              continue;
            }
          } catch {
            // Fall through to the named failure below: the folder that could
            // not be resolved is the one worth reporting.
          }
        }
        setFolderProgress(null);
        setUploadError(
          `Création du dossier « ${folder.name} » impossible : ${describeError(
            err,
            "réponse inattendue du serveur",
          )}`,
        );
        return;
      }
    }
    setFolderProgress(null);
    if (createdAny) invalidateLibrary();
    if (plan.tooDeep.length > 0) {
      setNotice(
        `${plan.tooDeep.length} fichier(s) ignoré(s) : arborescence trop profonde (max ${MAX_UPLOAD_DEPTH}).`,
      );
    }

    launchQueue(
      csrf,
      kept.map((item) => {
        const dir = parentDirOf(item.rel);
        return {
          file: item.file,
          rel: item.rel,
          folderId: dir ? (folderIds.get(dir) ?? currentFolderId) : currentFolderId,
        };
      }),
    );
  }

  function handleCancelUpload() {
    transfers.cancelAll();
  }

  function handleRetryFailed() {
    setUploadError(null);
    transfers.retryFailed();
  }

  function handleFilesChange(selected: FileList | File[] | null) {
    const list = selected ? Array.from(selected) : [];
    if (list.length === 0) return;
    setUploadError(null);
    setPendingFiles((current) => [...current, ...list]);
  }

  // Drop visual state (P0.3): a counter avoids flicker when crossing children.
  const [dragDepth, setDragDepth] = useState(0);

  /** Walk dropped entries: files keep their folder-relative path (P0.2).
   * Empty (0 o) files and empty folders are skipped, but counted, so the caller
   * can tell the two cases apart instead of showing one vague message. */
  async function collectDroppedEntries(
    items: DataTransferItemList,
    onProgress?: (files: number) => void,
  ): Promise<{
    entries: { file: File; rel: string }[];
    emptyFiles: number;
    emptyFolders: number;
  }> {
    const out: { file: File; rel: string }[] = [];
    let emptyFiles = 0;
    let emptyFolders = 0;
    // DataTransferItem access is only guaranteed during the drop dispatch:
    // capture every item synchronously before the first await, otherwise the
    // items after the first can be lost.
    const roots = Array.from(items).map((item) => ({
      entry: item.webkitGetAsEntry?.() ?? null,
      file: item.getAsFile(),
    }));
    const readBatch = (reader: FileSystemDirectoryReader) =>
      new Promise<FileSystemEntry[]>((resolve) => reader.readEntries(resolve));
    // Returns how many importable files this entry's subtree contributed.
    const walk = async (entry: FileSystemEntry, base: string): Promise<number> => {
      if (entry.isFile) {
        const file = await new Promise<File | null>((resolve) =>
          (entry as FileSystemFileEntry).file(resolve, () => resolve(null)),
        );
        if (!file) return 0;
        if (file.size === 0) {
          // A 0-o file is not importable: the backend refuses empty objects
          // unless the policy explicitly allows them (AURA_ALLOW_EMPTY_OBJECTS).
          emptyFiles += 1;
          return 0;
        }
        out.push({ file, rel: `${base}${entry.name}` });
        onProgress?.(out.length);
        return 1;
      }
      if (entry.isDirectory) {
        const reader = (entry as FileSystemDirectoryEntry).createReader();
        let found = 0;
        for (;;) {
          const batch = await readBatch(reader);
          if (batch.length === 0) break;
          for (const child of batch) {
            found += await walk(child, `${base}${entry.name}/`);
          }
        }
        // A dropped folder with no importable file anywhere is an empty folder.
        if (found === 0) emptyFolders += 1;
        return found;
      }
      return 0;
    };
    for (const root of roots) {
      if (root.entry) {
        await walk(root.entry, "");
        continue;
      }
      const file = root.file;
      if (!file) continue;
      if (file.size === 0) {
        emptyFiles += 1;
      } else {
        out.push({ file, rel: file.name });
        onProgress?.(out.length);
      }
    }
    return {
      entries: out.map(({ file, rel }) => ({
        file,
        rel: normalizeRelativePath(rel),
      })),
      emptyFiles,
      emptyFolders,
    };
  }

  /** Drop intake: loose files buffer, folders reuse the folder pipeline. */
  async function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragDepth(0);
    setIntakeOpen(true);
    setUploadError(null);
    setDropScan({ files: 0 });
    notify(
      "info",
      "Lecture du dépôt en cours — patientez pendant que les fichiers sont analysés.",
    );
    try {
      // Throttle: a large folder would otherwise re-render on every file.
      let lastReported = 0;
      const reportScan = (files: number) => {
        if (files === 1 || files - lastReported >= 25) {
          lastReported = files;
          setDropScan({ files });
        }
      };
      const { entries, emptyFiles, emptyFolders } = await collectDroppedEntries(
        e.dataTransfer.items,
        reportScan,
      );
      setDropScan(null);
      if (entries.length === 0) {
        // Distinguish a 0-o file from an empty folder, and recall the backend
        // policy (empty objects are refused unless explicitly allowed).
        const emptyFileNote =
          emptyFiles === 1
            ? "1 fichier vide (0 o) ignoré — le backend refuse les objets vides tant que la politique ne les autorise pas"
            : `${emptyFiles} fichiers vides (0 o) ignorés — le backend refuse les objets vides tant que la politique ne les autorise pas`;
        const emptyFolderNote =
          emptyFolders === 1
            ? "1 dossier vide ignoré (aucun fichier à l'intérieur)"
            : `${emptyFolders} dossiers vides ignorés (aucun fichier à l'intérieur)`;
        let message = "Aucun fichier importable dans ce dépôt.";
        if (emptyFiles > 0 && emptyFolders > 0) {
          message = `Aucun fichier importable : ${emptyFileNote}, et ${emptyFolderNote}.`;
        } else if (emptyFiles > 0) {
          message = `Aucun fichier importable : ${emptyFileNote}.`;
        } else if (emptyFolders > 0) {
          message = `Aucun fichier importable : ${emptyFolderNote}.`;
        }
        setUploadError(message);
        return;
      }
      const hasFolders = entries.some((entry) => entry.rel.includes("/"));
      if (transferActive) {
        const loose = entries.filter((entry) => !entry.rel.includes("/"));
        if (loose.length > 0) {
          // Buffer loose files for the next run and say so (P0.1): never
          // swallow a drop silently.
          setUploadError(null);
          setPendingFiles((current) => [
            ...current,
            ...loose.map((entry) => entry.file),
          ]);
          notify(
            "info",
            `Transfert en cours — ${
              loose.length === 1
                ? "1 fichier ajouté à la file d'attente."
                : `${loose.length} fichiers ajoutés à la file d'attente.`
            }` + (hasFolders ? " Les dossiers attendront la fin du transfert." : ""),
          );
        }
        if (hasFolders) {
          const folderEntries = entries.filter((entry) => entry.rel.includes("/"));
          setPendingFolderEntries((current) => [...current, ...folderEntries]);
          notify("info", "Transfert en cours — dossiers mis en attente, ils seront importés ensuite.");
        }
        if (loose.length === 0 && !hasFolders) {
          // Folder creation needs a free queue: say so instead of swallowing.
          setUploadError(
            "Un transfert est en cours : attendez sa fin pour déposer un dossier.",
          );
        }
        return;
      }
      if (hasFolders) {
        notify(
          "info",
          entries.length === 1
            ? "1 fichier prêt — préparation des dossiers…"
            : `${entries.length} fichiers prêts — préparation des dossiers…`,
        );
        await uploadRelPaths(
          entries.map((entry) => entry.file),
          entries.map((entry) => entry.rel),
        );
      } else {
        handleFilesChange(entries.map((entry) => entry.file));
      }
    } catch (error) {
      setUploadError(describeError(error, "Lecture du dépôt impossible."));
    } finally {
      setDropScan(null);
    }
  }

  function removePendingFile(index: number) {
    setPendingFiles((current) => current.filter((_, i) => i !== index));
  }

  async function handleDownload(item: ObjectItem) {
    setActionError(null);
    if (!csrf) {
      setActionError("Session expirée. Reconnectez-vous.");
      return;
    }
    setDownloadingId(item.id);
    // Open the tab inside the user gesture: after the await, popup blockers
    // (Firefox/Safari) refuse it even though the toast claimed success.
    const pendingWindow = window.open("about:blank", "_blank");
    try {
      const intent = await api.createDownloadIntent(item.id, csrf);
      // The browser performs the direct S3 GET; it manages its own progress.
      if (pendingWindow) {
        pendingWindow.opener = null;
        pendingWindow.location.replace(intent.download_url);
      } else {
        const link = document.createElement("a");
        link.href = intent.download_url;
        link.target = "_blank";
        link.rel = "noopener";
        link.download = intent.display_name;
        link.click();
      }
      notify(
        "ok",
        `Téléchargement de « ${intent.display_name} » lancé (${formatBytes(
          intent.size_bytes,
        )}).`,
      );
    } catch (err) {
      pendingWindow?.close();
      setActionError(`Téléchargement impossible. ${describeError(err, "")}`.trim());
    } finally {
      setDownloadingId(null);
    }
  }

  async function handleCopyReference(item: ObjectItem) {
    setActionError(null);
    try {
      await navigator.clipboard.writeText(item.id);
      notify("ok", `Référence copiée : ${item.id}`);
    } catch {
      setActionError("Copie impossible dans ce navigateur.");
    }
  }

  /** Folders that cannot be a move target: the folder itself and its subtree. */
  function forbiddenTargets(rootId: string): Set<string> {
    const out = new Set<string>([rootId]);
    const queue = [rootId];
    while (queue.length > 0) {
      const node = queue.shift();
      for (const child of childrenOf.get(node ?? null) ?? []) {
        if (!out.has(child.id)) {
          out.add(child.id);
          queue.push(child.id);
        }
      }
    }
    return out;
  }

  // Offset pagination refetches each loaded page at its old offset; if objects
  // were inserted at the top (an import finishing), the same row can appear on
  // two pages. Deduplicate by id so the ledger never shows a file twice or
  // loses one to a duplicate React key.
  const items = useMemo(() => {
    const seen = new Set<string>();
    const out: ObjectItem[] = [];
    for (const page of objectsQuery.data?.pages ?? []) {
      for (const item of page.items) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        out.push(item);
      }
    }
    return out;
  }, [objectsQuery.data]);

  // Répartition des statuts sur les pages déjà chargées. Elle ne peut pas
  // vivre dans le filtre d'état : celui-ci sert justement à charger les autres
  // statuts, donc un compteur y serait circulaire et partiel par construction.
  // `deleted` et `purging` n'apparaissent jamais sans filtre : l'API applique
  // `hide_deleted = status is None` et ne renvoie donc pas ces lignes.
  const statusTally = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of items) {
      counts.set(item.status, (counts.get(item.status) ?? 0) + 1);
    }
    return STATUS_OPTIONS.filter((option) => option.value !== "")
      .map((option) => ({ ...option, count: counts.get(option.value) ?? 0 }))
      .filter((entry) => entry.count > 0);
  }, [items]);

  // Only deletable rows are selectable: the server refuses anything else
  // with 409, so offering them would manufacture failures.
  // In master mode the trash can be selected too: its rows are purgeable.
  const selectableItems = items.filter(
    (item) => isDeletable(item) || (master.active && item.status === "deleted"),
  );
  const selectableIds = new Set(selectableItems.map((item) => item.id));

  const currentName = currentFolderId ? byId.get(currentFolderId)?.name : null;

  const moveBlocked = moveTarget ? forbiddenTargets(moveTarget.id) : new Set<string>();
  const deletePendingId = deleteObjectMutation.isPending
    ? deleteObjectMutation.variables
    : undefined;
  const purgePendingId = purgeMutation.isPending ? purgeMutation.variables : undefined;
  const abortPendingId = abortUploadMutation.isPending
    ? abortUploadMutation.variables
    : undefined;
  const objectBusy =
    deleteObjectMutation.isPending ||
    purgeMutation.isPending ||
    restoreMutation.isPending ||
    abortUploadMutation.isPending ||
    moveObjectMutation.isPending ||
    downloadingId !== null;

  // -- recursive (cascade) folder deletion ---------------------------------
  /** Keep the React state and the run-loop mirror in lockstep. */
  function applyCascade(next: CascadeState | null) {
    cascadeRef.current = next;
    setCascade(next);
  }

  /** Open the cascade flow for `target`: scan its real content first. */
  function openCascade(target: { id: string; name: string }) {
    setPendingConfirm(null);
    setFolderDeleteError(null);
    setFolderDeleteWithContent(false);
    setCascadeConfirmText("");
    cascadeCancelRef.current = false;
    applyCascade({
      rootId: target.id,
      rootName: target.name,
      phase: "scanning",
      plan: null,
      ops: [],
      done: 0,
      current: null,
      failures: [],
      cancelled: false,
      scanError: null,
    });
    void runCascadeScan(target.id, target.name);
  }

  /** List (never guess) the target's content; failure is surfaced, not hidden. */
  async function runCascadeScan(rootId: string, rootName: string) {
    const current = cascadeRef.current;
    if (!current) return;
    applyCascade({ ...current, phase: "scanning", plan: null, scanError: null });
    try {
      const plan = await scanCascade(rootId, rootName);
      const live = cascadeRef.current;
      if (!live || live.rootId !== rootId || live.phase !== "scanning") return;
      applyCascade({ ...live, phase: "confirm", plan, ops: planCascadeOps(plan) });
    } catch (err) {
      const live = cascadeRef.current;
      if (!live || live.rootId !== rootId || live.phase !== "scanning") return;
      applyCascade({
        ...live,
        phase: "confirm",
        scanError:
          err instanceof CascadeScanError
            ? `Analyse interrompue dans « ${err.path} ». ${describeError(
                err.cause,
                "Réessayez dans un instant.",
              )}`
            : `Analyse du contenu impossible. ${describeError(err, "Réessayez dans un instant.")}`,
      });
    }
  }

  /** The typed confirmation matched: start the confirmed run. */
  function startCascade() {
    const current = cascadeRef.current;
    if (!current || current.phase !== "confirm" || !current.plan) return;
    void executeCascade([...current.ops]);
  }

  /** Run the ordered steps sequentially, recording each real server outcome. */
  async function executeCascade(opsToRun: CascadeOp[]) {
    const start = cascadeRef.current;
    if (!start) return;
    const activeCsrf = csrf;
    if (!activeCsrf) {
      notify("error", "Session expirée. Reconnectez-vous pour supprimer.");
      applyCascade({
        ...start,
        phase: "done",
        current: null,
        scanError: "Session expirée.",
      });
      return;
    }
    cascadeCancelRef.current = false;
    let done = start.done;
    let failures = start.failures;
    applyCascade({ ...start, phase: "deleting", current: null, cancelled: false });

    for (const op of opsToRun) {
      if (cascadeCancelRef.current) {
        // Cancellation lands between items: whatever the server confirmed stays
        // deleted, nothing local is faked.
        const live = cascadeRef.current ?? start;
        applyCascade({ ...live, done, failures, current: null, cancelled: true });
        break;
      }
      const key = cascadeOpKey(op);
      applyCascade({
        ...(cascadeRef.current ?? start),
        done,
        failures,
        current: op.path,
      });
      try {
        if (op.kind === "object") await api.deleteObject(op.id, activeCsrf);
        else await api.deleteFolder(op.id, activeCsrf);
        done += 1;
        failures = failures.filter((failure) => failure.key !== key);
      } catch (err) {
        const detail = describeError(err, "Échec de suppression.");
        failures = [
          ...failures.filter((failure) => failure.key !== key),
          { key, kind: op.kind, id: op.id, label: op.label, path: op.path, error: detail },
        ];
      }
      applyCascade({
        ...(cascadeRef.current ?? start),
        done,
        failures,
        current: null,
      });
    }

    const end = cascadeRef.current ?? start;
    invalidateLibrary();
    applyCascade({ ...end, phase: "done", current: null });

    const final = cascadeRef.current;
    if (!final) return;
    if (final.cancelled) {
      notify(
        "info",
        `Suppression interrompue : ${final.done} élément(s) supprimé(s), ${final.failures.length} échec(s).`,
      );
    } else if (final.failures.length === 0) {
      notify("ok", `Dossier et contenu supprimés : ${final.done} élément(s).`);
    } else {
      notify(
        "error",
        `${final.done} élément(s) supprimé(s), ${final.failures.length} échec(s) : ouvrez le journal pour réessayer.`,
      );
    }
  }

  function retryCascadeFailures() {
    const current = cascadeRef.current;
    if (!current || current.phase !== "done" || current.failures.length === 0) return;
    void executeCascade(
      current.failures.map((failure) => ({
        kind: failure.kind,
        id: failure.id,
        label: failure.label,
        path: failure.path,
      })),
    );
  }

  function retryCascadeItem(failure: CascadeFailure) {
    const current = cascadeRef.current;
    if (!current || current.phase !== "done") return;
    void executeCascade([
      { kind: failure.kind, id: failure.id, label: failure.label, path: failure.path },
    ]);
  }

  function abandonCascadeItem(failure: CascadeFailure) {
    const current = cascadeRef.current;
    if (!current) return;
    applyCascade({
      ...current,
      failures: current.failures.filter((entry) => entry.key !== failure.key),
    });
  }

  /** Request a stop; it is honoured between items by the run loop. */
  function cancelCascade() {
    cascadeCancelRef.current = true;
  }

  function closeCascade() {
    if (cascadeRef.current?.phase === "deleting") {
      cascadeCancelRef.current = true;
      return;
    }
    applyCascade(null);
  }

  // The cascade modal is a native <dialog> so Escape/focus trapping come for
  // free; it is shown while a cascade state exists and closed when it clears.
  useEffect(() => {
    const el = cascadeDialogRef.current;
    if (!el) return;
    if (cascade && !el.open) {
      el.showModal();
    } else if (!cascade && el.open) {
      el.close();
    }
  }, [cascade]);

  // Details drawer: focus its close button on open and close it on Escape
  // from anywhere (focus may still be on the row that opened it). A modal
  // dialog stacked on top handles its own Escape first.
  const detailsCloseRef = useRef<HTMLButtonElement | null>(null);
  const detailsId = details?.id ?? null;
  useEffect(() => {
    if (!detailsId) return;
    detailsCloseRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || document.querySelector("dialog[open]")) return;
      setDetails(null);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [detailsId]);

  const intakeVisible =
    intakeOpen ||
    dropScan !== null ||
    pendingFiles.length > 0 ||
    pendingFolderEntries.length > 0 ||
    queue.items.length > 0 ||
    uploadError !== null;

  // Subfolders are listed first in the register, like any file browser; a
  // search or filter narrows files only, so folders step aside meanwhile.
  const visibleFolders = hasActiveFilters ? [] : subfolders;

  function folderMenuItems(folder: FolderItem) {
    return [
      {
        label: "Renommer",
        onSelect: () => {
          setRenameName(folder.name);
          setRenameTarget(folder);
        },
      },
      { label: "Déplacer", onSelect: () => setMoveTarget(folder) },
      {
        label: "Supprimer",
        danger: true,
        onSelect: () => {
          setFolderDeleteWithContent(false);
          setCascadeConfirmText("");
          setPendingConfirm({
            title: "Supprimer le dossier",
            message: (
              <>
                Supprimer <strong>{folder.name}</strong> ? Un dossier contenant
                encore des fichiers ou sous-dossiers sera refusé.
              </>
            ),
            confirmLabel: "Supprimer",
            danger: true,
            folderCascade: canCascadeDelete,
            onConfirm: (withContent: boolean) => {
              if (withContent) {
                openCascade({ id: folder.id, name: folder.name });
              } else {
                deleteFolderMutation.mutate({ id: folder.id, name: folder.name });
              }
            },
          });
        },
      },
    ];
  }

  /** A column header that sorts server-side: same column toggles the order. */
  function sortHeader(field: NonNullable<ObjectQuery["sort"]>) {
    const column = SORT_COLUMNS.find((entry) => entry.field === field);
    if (!column) return null;
    const active = sortField === field;
    return (
      <button
        type="button"
        className={active ? "sort-head sort-head-active" : "sort-head"}
        onClick={() => {
          if (active) {
            setSortOrder(sortOrder === "asc" ? "desc" : "asc");
          } else {
            setSortField(field);
            setSortOrder(column.firstOrder);
          }
        }}
      >
        {column.label}
        {active ? (
          <>
            <span aria-hidden="true" className="sort-arrow">
              {sortOrder === "asc" ? "▲" : "▼"}
            </span>
            <span className="visually-hidden">
              {sortOrder === "asc" ? " (tri croissant)" : " (tri décroissant)"}
            </span>
          </>
        ) : null}
      </button>
    );
  }

  const cascadeConfirmed =
    cascade !== null &&
    cascade.plan !== null &&
    cascade.rootName.trim() !== "" &&
    cascadeConfirmText.trim() === cascade.rootName.trim();

  return (
    <div
      className="stack vault-workspace"
      onDragEnter={(e) => {
        e.preventDefault();
        setDragDepth((depth) => depth + 1);
      }}
      onDragLeave={() => {
        setDragDepth((depth) => Math.max(0, depth - 1));
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDrop={(e) => {
        void handleDrop(e);
      }}
    >
      <nav className="breadcrumb" aria-label="Fil d'Ariane">
        <button
          type="button"
          className={currentFolderId === null ? "crumb crumb-current" : "crumb"}
          aria-current={currentFolderId === null ? "page" : undefined}
          onClick={() => setCurrentFolderId(null)}
        >
          Mes fichiers
        </button>
        {breadcrumb.map((folder, index) => (
          <span key={folder.id} className="crumb-item">
            <span className="crumb-sep" aria-hidden="true">
              /
            </span>
            <button
              type="button"
              className={
                index === breadcrumb.length - 1 ? "crumb crumb-current" : "crumb"
              }
              aria-current={index === breadcrumb.length - 1 ? "page" : undefined}
              onClick={() => setCurrentFolderId(folder.id)}
            >
              {folder.name}
            </button>
          </span>
        ))}
      </nav>

      <div className="page-head">
        <div className="page-title">
          <h1>{currentName ?? "Mes fichiers"}</h1>
          <p className="muted page-sub">
            {subfolders.length} dossier{subfolders.length > 1 ? "s" : ""} ·{" "}
            {items.length} fichier{items.length > 1 ? "s" : ""}
            {objectsQuery.hasNextPage ? " (d'autres restent à charger)" : ""}
          </p>
          <div className="control-bar">
            <span className="control-bar-label">Vue de contrôle</span>
            <span className="control-bar-stats">
              {items.length} fichier(s) · {queue.items.length} en cours
            </span>
            {phaseBadges.length > 0 ? (
              <span className="control-bar-badges">
                {phaseBadges.map((badge) => (
                  <span
                    key={badge.key}
                    className={`phase-badge phase-badge-${badge.tone}`}
                  >
                    {badge.label} · {badge.count}
                  </span>
                ))}
              </span>
            ) : null}
          </div>
        </div>
        <div className="head-actions">
          {/* Action primaire : toujours isolée, jamais noyée dans le groupe. */}
          {canCreate ? (
            <button
              type="button"
              className="btn btn-primary head-actions-primary"
              onClick={() => setIntakeOpen(true)}
            >
              Importer
            </button>
          ) : null}
          <div className="head-actions-group" role="group" aria-label="Actions courantes">
            {canCreateFolder ? (
              <button
                type="button"
                className="btn"
                onClick={() => setNewFolderOpen(true)}
              >
                Nouveau dossier
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-ghost"
              title="Actualiser la liste"
              aria-label="Actualiser la liste"
              disabled={objectsQuery.isFetching || treeQuery.isFetching}
              onClick={() => {
                setActionError(null);
                void queryClient.invalidateQueries({ queryKey: ["objects"] });
                void queryClient.invalidateQueries({ queryKey: ["folders"] });
              }}
            >
              {objectsQuery.isFetching ? "Actualisation…" : "Actualiser"}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              aria-label="Afficher les raccourcis clavier"
              title="Raccourcis clavier (?)"
              aria-keyshortcuts="?"
              aria-haspopup="dialog"
              onClick={() => setShortcutsOpen(true)}
            >
              ?
            </button>
          </div>
          {canPurge && !master.active ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setMasterDialogOpen(true)}
            >
              Mode maître
            </button>
          ) : null}
          {master.active && statusFilter === "deleted" ? (
            <button
              type="button"
              className="btn btn-danger"
              disabled={emptyTrashMutation.isPending}
              onClick={() => emptyTrashMutation.mutate()}
            >
              {emptyTrashMutation.isPending ? (
                <span className="spinner" aria-hidden="true" />
              ) : null}
              {emptyTrashMutation.isPending ? "Vidage…" : "Vider la corbeille"}
            </button>
          ) : null}
        </div>
      </div>

      <VaultOverview
        usage={usageQuery.data}
        formatBytes={formatBytes}
        measuredLabel={usageQuery.data ? formatDateTime(usageQuery.data.measured_at) : ""}
      />

      {actionError ? (
        <p role="alert" className="alert alert-error">
          {actionError}
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => setActionError(null)}
          >
            Fermer
          </button>
        </p>
      ) : null}

      {master.active ? (
        <MasterModeBanner secondsLeft={master.secondsLeft} csrf={csrf} />
      ) : null}

      {resumable.length > 0 && !transferActive ? (
        <div role="region" aria-label="Import interrompu" className="alert alert-warn resume-banner">
          <p>
            <strong>Import interrompu</strong> : {resumable.length} fichier(s) restant(s) (
            {formatBytes(resumable.reduce((sum, entry) => sum + entry.size, 0))}). Choisissez
            à nouveau les mêmes fichiers ou le même dossier : seuls ceux qui manquent
            seront envoyés.
          </p>
          <div className="resume-actions">
            <button
              type="button"
              className="btn btn-primary btn-small"
              onClick={() => resumeFilesRef.current?.click()}
            >
              Reprendre avec des fichiers…
            </button>
            <button
              type="button"
              className="btn btn-small"
              onClick={() => resumeDirRef.current?.click()}
            >
              Reprendre avec un dossier…
            </button>
            <button type="button" className="btn btn-ghost btn-small" onClick={forgetResumable}>
              Oublier
            </button>
          </div>
          <input
            ref={resumeFilesRef}
            type="file"
            multiple
            data-testid="resume-files-input"
            className="visually-hidden"
            onChange={(e) => {
              handleResume(e.target.files);
              e.target.value = "";
            }}
          />
          <input
            ref={resumeDirRef}
            type="file"
            multiple
            data-testid="resume-folder-input"
            className="visually-hidden"
            onChange={(e) => {
              handleResume(e.target.files);
              e.target.value = "";
            }}
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          />
        </div>
      ) : null}
      {notice ? (
        <p role="status" className="alert alert-ok">
          {notice}
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => setNotice(null)}
          >
            Fermer
          </button>
        </p>
      ) : null}

      {folderDeleteError ? (
        <p role="alert" className="alert alert-error">
          Le dossier «&nbsp;{folderDeleteError.name}&nbsp;» n'est pas vide : supprimez
          ou déplacez d'abord ses fichiers et sous-dossiers, puis réessayez.
          {canCascadeDelete ? (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => openCascade(folderDeleteError)}
            >
              Supprimer avec son contenu…
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-ghost btn-small"
            disabled={deleteFolderMutation.isPending}
            onClick={() => deleteFolderMutation.mutate(folderDeleteError)}
          >
            {deleteFolderMutation.isPending ? "Suppression…" : "Réessayer"}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => setFolderDeleteError(null)}
          >
            Fermer
          </button>
        </p>
      ) : null}

      {treeQuery.isError ? (
        <p role="alert" className="alert alert-error">
          Dossiers indisponibles.
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => void treeQuery.refetch()}
          >
            Réessayer
          </button>
        </p>
      ) : null}

      {/* Admin-only query: surface a real failure instead of leaving the
          readout blank (non-admins are silently skipped — no error). */}
      {hasAdminAccess(session.data?.role) && usageQuery.isError ? (
        <p role="alert" className="alert alert-error">
          Espace utilisé indisponible.
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => void usageQuery.refetch()}
          >
            Réessayer
          </button>
        </p>
      ) : null}

      {dragDepth > 0 ? (
        <div className="drop-overlay" role="status">
          <p className="drop-hint">
            Relâchez pour importer{currentName ? ` dans « ${currentName} »` : ""} —
            dossiers acceptés.
          </p>
        </div>
      ) : null}

      <section
        id="intake"
        className="card intake"
        aria-labelledby="upload-title"
        hidden={!intakeVisible}
      >
        <div className="intake-head">
          <h2 id="upload-title">
            Importer{currentName ? ` dans « ${currentName} »` : ""}
          </h2>
          {!transferActive && pendingFiles.length === 0 && dropScan === null ? (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => {
                setIntakeOpen(false);
                setUploadError(null);
                if (queue.finished) transfers.clear();
              }}
            >
              Fermer
            </button>
          ) : null}
        </div>
        <p className="muted">
          Déposez des fichiers ou des dossiers n'importe où sur la page, ou
          choisissez-les. Un fichier n'est déclaré disponible qu'une fois sa
          taille et son empreinte SHA-256 vérifiées par le serveur.
        </p>
        {dropScan ? (
          <p className="pending-hint import-scan" role="status">
            <span className="spinner" aria-hidden="true" />
            <span>
              Lecture du dépôt en cours…{" "}
              {dropScan.files === 1
                ? "1 fichier trouvé. "
                : dropScan.files > 1
                  ? `${dropScan.files} fichiers trouvés. `
                  : null}
              Patientez pendant que les fichiers sont analysés — rien n'est encore
              envoyé.
            </span>
          </p>
        ) : null}
        {folderProgress ? (
          <p className="pending-hint" role="status">
            Arborescence : dossier {folderProgress.done + 1}/
            {folderProgress.total} — «&nbsp;{folderProgress.name}&nbsp;»
          </p>
        ) : null}
        <form onSubmit={handleUpload} className="form form-inline">
          <div className="field file-field">
            <span>Fichiers</span>
            <label className="file-picker">
              <input
                type="file"
                name="files"
                multiple
                data-testid="files-input"
                className="visually-hidden"
                disabled={transferActive}
                onChange={(e) => {
                  handleFilesChange(e.target.files);
                  e.target.value = "";
                }}
              />
              <span className="btn">Choisir des fichiers…</span>
              <span className="file-picker-name">
                {pendingFiles.length === 0
                  ? "Aucun fichier sélectionné"
                  : pendingFiles.length === 1
                    ? (pendingFiles[0]?.name ?? "")
                    : `${pendingFiles.length} fichiers sélectionnés`}
              </span>
            </label>
          </div>
          <input
            ref={dirInputRef}
            type="file"
            multiple
            data-testid="folder-input"
            className="visually-hidden"
            disabled={transferActive}
            onChange={(e) => {
              void handleFolderUpload(e.target.files);
              e.target.value = "";
            }}
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          />
          <button
            type="button"
            className="btn"
            disabled={transferActive}
            onClick={() => dirInputRef.current?.click()}
          >
            Importer un dossier…
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={pendingFiles.length === 0 && pendingFolderEntries.length === 0}
          >
            {transferActive ? "Transfert…" : "Importer et valider"}
          </button>
          {transferActive ? (
            <ConfirmAction
              label="Annuler"
              title="Arrêter l'import ?"
              message={
                <>
                  {queue.items.length - queue.done} fichier(s) sur {queue.items.length} ne sont
                  pas encore transférés ({formatBytes(
                    queue.items.reduce(
                      (sum, item) => sum + (item.state.phase === "available" ? 0 : item.sizeBytes),
                      0,
                    ),
                  )}). Les envois en cours sont interrompus ; les fichiers déjà validés restent.
                </>
              }
              confirmLabel="Arrêter l'import"
              danger
              className="btn"
              onConfirm={handleCancelUpload}
            />
          ) : null}
          {queue.failed > 0 || (!transferActive && queue.cancelled > 0) ? (
            <button type="button" className="btn" onClick={handleRetryFailed}>
              Réessayer les échecs
            </button>
          ) : null}
        </form>

        {pendingFolderEntries.length > 0 ? (
          <div className="pending-folders">
            <p className="pending-hint" role="status">
              Dossiers en attente :{" "}
              {Array.from(new Set(pendingFolderEntries.map((e) => e.rel.split("/")[0]))).join(", ")}{" "}
              — {pendingFolderEntries.length} fichier(s).
            </p>
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => setPendingFolderEntries([])}
            >
              Retirer les dossiers
            </button>
          </div>
        ) : null}
        {pendingFiles.length > 0 ? (
          <>
            {transferActive ? (
              <p className="pending-hint" role="status">
                En attente du prochain import — le transfert en cours se termine
                d'abord.
              </p>
            ) : null}
            <ul className="pending">
              {pendingFiles.map((pending, index) => (
                <li key={`${pending.name}-${index}`} className="pending-item">
                  <span className="transfer-name">{pending.name}</span>
                  <span className="muted">{formatBytes(pending.size)}</span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    aria-label={`Retirer ${pending.name}`}
                    onClick={() => removePendingFile(index)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : null}

        {uploadError ? (
          <p role="alert" className="alert alert-error">
            {uploadError}
          </p>
        ) : null}
        {queue.finished &&
        queue.items.length > 0 &&
        queue.done === queue.items.length ? (
          <p role="status" className="alert alert-ok">
            Import validé et vérifié par le backend.
          </p>
        ) : null}
        {queue.finished &&
        queue.items.length > 0 &&
        queue.cancelled === queue.items.length ? (
          <p role="status" className="alert">
            Import annulé.
          </p>
        ) : null}
      </section>

      <section className="section" aria-labelledby="objects-title">
        <div className="section-head">
          <h2 id="objects-title" className="visually-hidden">
            Contenu — {currentName ?? "racine"}
          </h2>
          <span className="visually-hidden" aria-live="polite">
            {items.length} fichier{items.length > 1 ? "s" : ""} affiché
            {items.length > 1 ? "s" : ""}
          </span>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => setPacksOpen(true)}
          >
            Packs
          </button>
          <div className="view-toggle" role="group" aria-label="Affichage">
            <button
              type="button"
              className={viewMode === "list" ? "btn btn-small btn-primary" : "btn btn-small"}
              aria-pressed={viewMode === "list"}
              onClick={() => setViewMode("list")}
            >
              Liste
            </button>
            <button
              type="button"
              className={viewMode === "grid" ? "btn btn-small btn-primary" : "btn btn-small"}
              aria-pressed={viewMode === "grid"}
              onClick={() => setViewMode("grid")}
            >
              Grille
            </button>
          </div>
        </div>

        <form
          className="filters"
          role="search"
          onSubmit={(e) => e.preventDefault()}
          aria-label="Recherche et filtres"
        >
          <label className="field">
            <span>Rechercher</span>
            <input
              type="search"
              name="filter"
              placeholder="Nom du fichier…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="field">
            <span>État</span>
            <select
              name="status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn filters-toggle"
            aria-expanded={advancedOpen}
            aria-controls="advanced-filters"
            onClick={() => setAdvancedOpen((value) => !value)}
          >
            Filtres
            {advancedCount > 0 ? (
              <span className="filters-count">{advancedCount}</span>
            ) : null}
          </button>
          <button
            type="button"
            className="btn btn-small"
            onClick={resetFilters}
            disabled={!hasActiveFilters}
          >
            Réinitialiser
          </button>
        </form>

        {advancedOpen ? (
          <div className="filters-advanced" id="advanced-filters">
            <label className="field">
              <span>Type MIME</span>
              <input
                type="text"
                name="contentType"
                list="content-type-options"
                placeholder="application/pdf…"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
              />
              <datalist id="content-type-options">
                {CONTENT_TYPE_SUGGESTIONS.map((type) => (
                  <option key={type} value={type} />
                ))}
              </datalist>
            </label>
            <label className="field">
              <span>Taille min (o)</span>
              <input
                type="number"
                name="minSize"
                min={0}
                value={minSize}
                onChange={(e) => setMinSize(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Taille max (o)</span>
              <input
                type="number"
                name="maxSize"
                min={0}
                value={maxSize}
                onChange={(e) => setMaxSize(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Créé après le</span>
              <input
                type="date"
                name="from"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Créé avant le</span>
              <input
                type="date"
                name="to"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
              />
            </label>
          </div>
        ) : null}

        {statusFilter === "" ? (
          statusTally.length > 0 ? (
            <div className="filters-tally">
              <span className="filters-tally-label">Répartition chargée</span>
              <span className="filters-tally-list">
                {statusTally.map((entry) => (
                  <span
                    key={entry.value}
                    className={`filters-tally-item ${statusVariantClass(entry.value)}`}
                  >
                    {`${entry.label} · ${entry.count}`}
                  </span>
                ))}
              </span>
              {objectsQuery.hasNextPage ? (
                <span
                  className="filters-tally-note"
                  title="Décompte partiel : toutes les pages ne sont pas encore chargées."
                >
                  Partielle
                  <span className="visually-hidden">
                    {" — toutes les pages ne sont pas encore chargées"}
                  </span>
                </span>
              ) : null}
            </div>
          ) : null
        ) : null}

        {objectsQuery.isError ? (
          <p role="alert" className="alert alert-error">
            Catalogue indisponible. Aucune donnée en cache n'est présentée comme
            actuelle.
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => void objectsQuery.refetch()}
            >
              Réessayer
            </button>
          </p>
        ) : objectsQuery.isPending ? (
          <div className="ledger skeleton" role="status" aria-label="Chargement du catalogue">
            <span className="visually-hidden">Chargement du catalogue…</span>
            {Array.from({ length: 6 }).map((_, index) => (
              <div className="skeleton-row" key={index} aria-hidden="true">
                <div className="skeleton-bar" />
                <div className="skeleton-bar" />
                <div className="skeleton-bar" />
                <div className="skeleton-bar" />
                <div className="skeleton-bar" />
                <div className="skeleton-bar" />
              </div>
            ))}
          </div>
        ) : items.length === 0 && visibleFolders.length === 0 ? (
          <div className="empty empty-rich">
            <span className="empty-mark" aria-hidden="true">
              <FileTypeIcon contentType={hasActiveFilters ? "" : "application/pdf"} />
            </span>
            <p className="empty-title">
              {hasActiveFilters
                ? "Aucun fichier ne correspond à ces critères."
                : "Aucun fichier dans ce dossier."}
            </p>
            {!hasActiveFilters ? (
              <>
                <p className="muted empty-help">
                  Glissez des fichiers ou des dossiers n'importe où sur la page. Chaque
                  fichier n'est déclaré disponible qu'une fois sa taille et son empreinte
                  SHA-256 vérifiées par le serveur.
                </p>
                {canCreate ? (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => setIntakeOpen(true)}
                  >
                    Importer des fichiers
                  </button>
                ) : null}
              </>
            ) : null}
          </div>
        ) : (
          <>
            {selectedIds.size > 0 ? (
              <p role="status" className="alert">
                {selectedIds.size === 1
                  ? "1 objet sélectionné."
                  : `${selectedIds.size} objets sélectionnés.`}{" "}
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  disabled={deleteManyMutation.isPending}
                  onClick={() => setSelectedIds(new Set())}
                >
                  Tout désélectionner
                </button>{" "}
                {master.active ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-danger btn-small"
                      disabled={bulkPurgeMutation.isPending}
                      onClick={() => bulkPurgeMutation.mutate([...selectedIds])}
                    >
                      {bulkPurgeMutation.isPending ? (
                        <span className="spinner" aria-hidden="true" />
                      ) : null}
                      {bulkPurgeMutation.isPending
                        ? "Purge…"
                        : `Purger définitivement (${selectedIds.size})`}
                    </button>{" "}
                  </>
                ) : null}
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={deleteManyMutation.isPending}
                  onClick={() => setBulkDeleteOpen(true)}
                >
                  {deleteManyMutation.isPending && deleteManyProgress
                    ? `Suppression ${deleteManyProgress.done}/${deleteManyProgress.total}…`
                    : "Supprimer la sélection"}
                </button>
                {deleteManyProgress ? (
                  <span role="status" className="muted">
                    {" "}
                    Suppression {deleteManyProgress.done}/
                    {deleteManyProgress.total}…
                  </span>
                ) : null}
              </p>
            ) : null}
            {viewMode === "grid" ? (
              <div className="object-grid" role="list">
                {items.map((item) => (
                  <div className="object-card" key={item.id} role="listitem">
                    <input
                      type="checkbox"
                      className="object-card-check"
                      aria-label={`Sélectionner ${item.display_name}`}
                      checked={selectedIds.has(item.id)}
                      onChange={(e) =>
                        setSelectedIds((current) => {
                          const next = new Set(current);
                          if (e.target.checked) next.add(item.id);
                          else next.delete(item.id);
                          return next;
                        })
                      }
                    />
                    <button
                      type="button"
                      className="object-card-open"
                      onClick={() => setDetails(item)}
                      aria-label={`Détails de ${item.display_name}`}
                    >
                      <span className={`object-card-media file-tile-${fileKind(item.content_type)}`}>
                        <FileTypeIcon contentType={item.content_type} />
                        {item.thumbnail ? (
                          <img
                            src={`/api/v1/objects/${item.id}/thumbnail`}
                            alt=""
                            loading="lazy"
                            onError={(e) => {
                              e.currentTarget.style.display = "none";
                            }}
                          />
                        ) : null}
                        {item.duration_seconds ? (
                          <span className="object-card-duration">
                            {formatDuration(item.duration_seconds)}
                          </span>
                        ) : null}
                      </span>
                      <span className="object-card-name">{item.display_name}</span>
                      <span className="muted object-card-meta">
                        {typeLabel(item.content_type)} ·{" "}
                        {formatBytes(item.size_bytes)}
                      </span>
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="ledger" role="list" hidden={viewMode === "grid"}>
            <div className="ledger-head" role="listitem">
              <span>
                <input
                  type="checkbox"
                  aria-label="Tout sélectionner"
                  checked={
                    selectableItems.length > 0 &&
                    selectableItems.every((item) => selectedIds.has(item.id))
                  }
                  disabled={
                    selectableItems.length === 0 || deleteManyMutation.isPending
                  }
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedIds(
                        new Set(selectableItems.map((item) => item.id)),
                      );
                    } else {
                      setSelectedIds(new Set());
                    }
                  }}
                />{" "}
                {sortHeader("display_name")}
              </span>
              <span aria-hidden="true">Type</span>
              {sortHeader("size_bytes")}
              <span aria-hidden="true">État</span>
              {sortHeader("created_at")}
              <span aria-hidden="true" />
            </div>
            {visibleFolders.map((folder) => (
              <div className="ledger-row folder-row" role="listitem" key={folder.id}>
                <div className="ledger-name">
                  <span className="check-spacer" aria-hidden="true" />
                  <button
                    type="button"
                    className="folder-open"
                    onClick={() => setCurrentFolderId(folder.id)}
                  >
                    <span className="folder-icon" aria-hidden="true">
                      <FolderMark />
                    </span>
                    <span className="folder-name">{folder.name}</span>
                  </button>
                </div>
                <div className="ledger-meta">
                  <span className="ledger-type">Dossier</span>
                  <span className="ledger-size num">—</span>
                  <span className="ledger-status" />
                  <span className="ledger-date num">
                    {formatDateTime(folder.created_at)}
                  </span>
                </div>
                <div className="ledger-menu">
                  <RowMenu
                    label={`Actions pour le dossier ${folder.name}`}
                    items={folderMenuItems(folder)}
                  />
                </div>
              </div>
            ))}
            {items.map((item) => {
              const rowBusy =
                deletePendingId === item.id ||
                purgePendingId === item.id ||
                abortPendingId === item.id ||
                downloadingId === item.id;
              return (
                <div className="ledger-row" role="listitem" key={item.id}>
                  <div className="ledger-name">
                    <input
                      type="checkbox"
                      aria-label={`Sélectionner ${item.display_name}`}
                      checked={selectedIds.has(item.id)}
                      disabled={
                        !selectableIds.has(item.id) ||
                        deleteManyMutation.isPending
                      }
                      onChange={(e) => {
                        setSelectedIds((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) {
                            next.add(item.id);
                          } else {
                            next.delete(item.id);
                          }
                          return next;
                        });
                      }}
                    />{" "}
                    <span
                      className={`file-tile file-tile-${fileKind(item.content_type)}`}
                      aria-hidden="true"
                    >
                      <FileTypeIcon contentType={item.content_type} />
                    </span>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setDetails(item)}
                      aria-label={`Détails de ${item.display_name}`}
                    >
                      {item.display_name}
                    </button>
                  </div>
                  <div className="ledger-meta">
                    <span className="ledger-type" title={item.content_type}>
                      <FileTypeIcon contentType={item.content_type} />{" "}
                      {typeLabel(item.content_type)}
                    </span>
                    <span className="ledger-size num">
                      {formatBytes(
                        item.status === "pending" && item.expected_size_bytes != null
                          ? item.expected_size_bytes
                          : item.size_bytes,
                      )}
                    </span>
                    <span className="ledger-status">
                      <StatusLabel status={item.status} />
                    </span>
                    <span className="ledger-date num">
                      {formatDateTime(item.created_at)}
                    </span>
                  </div>
                  <div className="ledger-menu">
                    <RowMenu
                      label={`Actions pour ${item.display_name}`}
                      items={[
                        { label: "Détails", onSelect: () => setDetails(item) },
                        ...(item.status === "available" && isPreviewable(item.content_type)
                          ? [{ label: "Aperçu", onSelect: () => setPreviewTarget(item) }]
                          : []),
                        {
                          label: "Télécharger",
                          disabled:
                            item.status !== "available" || downloadingId !== null,
                          onSelect: () => void handleDownload(item),
                        },
                        ...(canShare && item.status === "available"
                          ? [{ label: "Partager", onSelect: () => setShareTarget(item) }]
                          : []),
                        ...(canShare && item.status === "available"
                          ? [{ label: "Publier", onSelect: () => setPublishTarget(item) }]
                          : []),
                        {
                          label: "Copier la référence",
                          onSelect: () => void handleCopyReference(item),
                        },
                        {
                          label: "Déplacer",
                          disabled: rowBusy,
                          onSelect: () => setMoveObjectTarget(item),
                        },
                        ...(item.status === "pending"
                          ? [
                              {
                                label: "Abandonner l'envoi",
                                danger: true,
                                disabled: rowBusy,
                                onSelect: () =>
                                  setPendingConfirm({
                                    title: "Abandonner l'envoi",
                                    message: (
                                      <>
                                        Abandonner l'envoi de{" "}
                                        <strong>{item.display_name}</strong> ?
                                        Les octets partiels seront supprimés.
                                        Pour réessayer, importez à nouveau le
                                        fichier.
                                      </>
                                    ),
                                    confirmLabel: "Abandonner",
                                    danger: true,
                                    onConfirm: () =>
                                      abortUploadMutation.mutate(item.id),
                                  }),
                              },
                            ]
                          : []),
                        ...(isRestorable(item)
                          ? [
                              {
                                label: "Restaurer",
                                disabled: objectBusy,
                                onSelect: () => restoreMutation.mutate(item.id),
                              },
                            ]
                          : []),
                        {
                          label: "Supprimer",
                          danger: true,
                          // Same rule as the bulk selection (available|pending):
                          // the server 409s every other status, so an enabled
                          // entry here would only manufacture a failure.
                          disabled: objectBusy || !isDeletable(item),
                          onSelect: () =>
                            setPendingConfirm({
                              title: "Supprimer l'objet",
                              message: (
                                <>
                                  Marquer <strong>{item.display_name}</strong> comme
                                  supprimé ? Les octets restent jusqu'à une purge.
                                </>
                              ),
                              confirmLabel: "Supprimer",
                              danger: true,
                              onConfirm: () => deleteObjectMutation.mutate(item.id),
                            }),
                        },
                        ...(canPurge
                          ? [
                              {
                                label: "Purger définitivement",
                                danger: true,
                                disabled: objectBusy,
                                // Master mode: no confirmation per item.
                                onSelect: () =>
                                  master.active
                                    ? purgeMutation.mutate(item.id)
                                    : setPendingConfirm({
                                        title: "Purger définitivement",
                                        message: (
                                          <>
                                            Supprimer définitivement{" "}
                                            <strong>{item.display_name}</strong> et ses
                                            octets ? Action irréversible.
                                          </>
                                        ),
                                        confirmLabel: "Purger",
                                        danger: true,
                                        onConfirm: () => purgeMutation.mutate(item.id),
                                      }),
                              },
                            ]
                          : []),
                      ]}
                    />
                  </div>
                </div>
                  );
            })}
          </div>
          </>
        )}
        {objectsQuery.hasNextPage ? (
          <div className="load-more" ref={loadMoreRef}>
            <button
              type="button"
              className="btn"
              disabled={objectsQuery.isFetchingNextPage}
              onClick={() => void objectsQuery.fetchNextPage()}
            >
              {objectsQuery.isFetchingNextPage ? "Chargement…" : "Charger plus"}
            </button>
          </div>
        ) : null}
      </section>

      {/* Object details side panel (only fields the API actually exposes). */}
      {details ? (
        <>
          <div
            className="drawer-scrim"
            aria-hidden="true"
            onClick={() => setDetails(null)}
          />
          <aside
            className="drawer"
            role="dialog"
            aria-modal="false"
            aria-labelledby="details-title"
          >
          <div className="drawer-head">
            <span
              className={`file-tile file-tile-lg file-tile-${fileKind(details.content_type)}`}
              aria-hidden="true"
            >
              <FileTypeIcon contentType={details.content_type} />
            </span>
            <div className="drawer-title">
              <span className="muted">{typeLabel(details.content_type)}</span>
              <h2 id="details-title">{details.display_name}</h2>
            </div>
            <button
              ref={detailsCloseRef}
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => setDetails(null)}
              aria-label="Fermer les détails"
            >
              Fermer
            </button>
          </div>
          <div
            className={`drawer-banner drawer-banner-${
              details.status === "available"
                ? "ok"
                : details.status === "pending"
                  ? "run"
                  : details.status === "failed"
                    ? "error"
                    : "muted"
            }`}
          >
            <strong>
              {details.status === "available"
                ? "Disponible et vérifié"
                : (STATUS_LABELS[details.status] ?? details.status)}
            </strong>
            <span>
              {details.status === "available"
                ? "Taille et SHA-256 contrôlés à l'import."
                : details.status === "pending"
                  ? "L'envoi n'est pas terminé : rien n'est téléchargeable."
                  : details.status === "deleted"
                    ? "Les octets restent jusqu'à une purge."
                    : "Ce fichier n'est pas utilisable en l'état."}
            </span>
          </div>
          <div className="drawer-actions">
            {details.status === "available" && isPreviewable(details.content_type) ? (
              <button
                type="button"
                className="btn"
                onClick={() => setPreviewTarget(details)}
              >
                Aperçu
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-primary"
              disabled={details.status !== "available" || downloadingId !== null}
              onClick={() => void handleDownload(details)}
            >
              {downloadingId === details.id ? "…" : "Télécharger"}
            </button>
            {canShare && details.status === "available" ? (
              <>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setShareTarget(details)}
                >
                  Partager
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setPublishTarget(details)}
                >
                  Publier
                </button>
              </>
            ) : null}
            {isRestorable(details) ? (
              <button
                type="button"
                className="btn btn-primary"
                disabled={objectBusy}
                onClick={() => restoreMutation.mutate(details.id)}
              >
                Restaurer
              </button>
            ) : null}
            <button
              type="button"
              className="btn"
              disabled={objectBusy}
              onClick={() => setMoveObjectTarget(details)}
            >
              Déplacer
            </button>
          </div>
          <ObjectAnalytics objectId={details.id} />
          <TagsEditor
            item={details}
            csrf={csrf}
            onSaved={() => {
              void queryClient.invalidateQueries({ queryKey: ["objects"] });
              void objectsQuery.refetch();
            }}
            onNotify={notify}
          />
          <dl className="detail-list">
            <dt>Taille</dt>
            <dd>
              {formatBytes(details.size_bytes)}
              <span className="muted"> ({details.size_bytes} octets)</span>
            </dd>
            <dt>Dossier</dt>
            <dd>{folderPath(details.folder_id)}</dd>
            <dt>Ajouté le</dt>
            <dd>{formatDateTime(details.created_at)}</dd>
            <dt>Modifié le</dt>
            <dd>{formatDateTime(details.updated_at)}</dd>
            <dt>Type MIME</dt>
            <dd className="mono">{details.content_type}</dd>
            <dt>Empreinte SHA-256</dt>
            <dd className="detail-hash">
              {details.checksum_sha256 ? (
                <>
                  <code className="mono">{details.checksum_sha256}</code>
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={() => {
                      const value = details.checksum_sha256;
                      if (!navigator.clipboard) {
                        notify("error", "Copie impossible : contexte non sécurisé.");
                        return;
                      }
                      void navigator.clipboard.writeText(value).then(
                        () => notify("ok", "Empreinte SHA-256 copiée."),
                        () => notify("error", "Copie refusée par le navigateur."),
                      );
                    }}
                  >
                    Copier
                  </button>
                </>
              ) : (
                "non disponible"
              )}
            </dd>
            <dt>Référence</dt>
            <dd className="detail-hash">
              <code className="mono">{details.id}</code>
              <button
                type="button"
                className="btn btn-small"
                onClick={() => void handleCopyReference(details)}
              >
                Copier la référence
              </button>
            </dd>
          </dl>
          <div className="drawer-danger">
            <h3>Zone sensible</h3>
            <div className="drawer-actions">
              <ConfirmAction
                label="Supprimer"
                title="Supprimer l'objet"
                message={
                  <>
                    Marquer <strong>{details.display_name}</strong> comme supprimé ?
                    Les octets restent jusqu'à une purge.
                  </>
                }
                confirmLabel="Supprimer"
                danger
                className="btn btn-danger-outline"
                disabled={objectBusy}
                pending={deletePendingId === details.id}
                onConfirm={() => deleteObjectMutation.mutate(details.id)}
              />
              {canPurge ? (
                <ConfirmAction
                  label="Purger définitivement"
                  title="Purger définitivement"
                  message={
                    <>
                      Supprimer définitivement <strong>{details.display_name}</strong>{" "}
                      et ses octets ? Action irréversible.
                    </>
                  }
                  confirmLabel="Purger"
                  danger
                  className="btn btn-danger-text"
                  disabled={objectBusy}
                  pending={purgePendingId === details.id}
                  onConfirm={() => purgeMutation.mutate(details.id)}
                />
              ) : null}
            </div>
            <p className="muted">
              La purge efface les octets et ne peut pas être annulée.
            </p>
          </div>
          </aside>
        </>
      ) : null}

      {/* New folder */}
      <Dialog
        open={newFolderOpen}
        title="Nouveau dossier"
        onClose={() => setNewFolderOpen(false)}
      >
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            createFolderMutation.mutate(newFolderName);
          }}
        >
          <label className="field">
            <span>Nom</span>
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              required
              autoFocus
            />
          </label>
          <div className="dialog-actions">
            <button
              type="button"
              className="btn"
              onClick={() => setNewFolderOpen(false)}
            >
              Annuler
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={createFolderMutation.isPending}
            >
              Créer
            </button>
          </div>
        </form>
      </Dialog>

      {/* Rename folder */}
      <Dialog
        open={renameTarget !== null}
        title="Renommer le dossier"
        onClose={() => setRenameTarget(null)}
      >
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            if (renameTarget) {
              renameMutation.mutate({ id: renameTarget.id, name: renameName });
            }
          }}
        >
          <label className="field">
            <span>Nom</span>
            <input
              type="text"
              value={renameName}
              onChange={(e) => setRenameName(e.target.value)}
              required
              autoFocus
            />
          </label>
          <div className="dialog-actions">
            <button
              type="button"
              className="btn"
              onClick={() => setRenameTarget(null)}
            >
              Annuler
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={renameMutation.isPending}
            >
              Renommer
            </button>
          </div>
        </form>
      </Dialog>

      {/* Move folder */}
      <Dialog
        open={moveTarget !== null}
        title="Déplacer le dossier"
        onClose={() => setMoveTarget(null)}
      >
        <p className="muted">
          Choisissez le nouveau dossier parent de « {moveTarget?.name} ».
        </p>
        <ul className="move-list">
          <li>
            <button
              type="button"
              className="btn btn-small"
              disabled={moveMutation.isPending}
              onClick={() =>
                moveTarget && moveMutation.mutate({ id: moveTarget.id, parentId: null })
              }
            >
              Racine
            </button>
          </li>
          {tree
            .filter((f) => !moveBlocked.has(f.id))
            .map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={moveMutation.isPending}
                  onClick={() =>
                    moveTarget &&
                    moveMutation.mutate({ id: moveTarget.id, parentId: f.id })
                  }
                >
                  {f.name}
                </button>
              </li>
            ))}
        </ul>
      </Dialog>

      {/* Move an object into a folder */}
      <Dialog
        open={moveObjectTarget !== null}
        title="Déplacer l'objet"
        onClose={() => setMoveObjectTarget(null)}
      >
        <p className="muted">
          Choisissez le dossier de destination de «{" "}
          {moveObjectTarget?.display_name} ».
        </p>
        {tree.length === 0 ? (
          <p className="empty">
            Aucun dossier pour l'instant. Créez-en un depuis la barre d'actions.
          </p>
        ) : (
          <ul className="move-list">
            <li>
              <button
                type="button"
                className="btn btn-small"
                disabled={moveObjectMutation.isPending}
                onClick={() =>
                  moveObjectTarget &&
                  moveObjectMutation.mutate({
                    id: moveObjectTarget.id,
                    folderId: null,
                  })
                }
              >
                Racine (sans dossier)
              </button>
            </li>
            {tree.map((folder) => (
              <li key={folder.id}>
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={
                    moveObjectMutation.isPending ||
                    moveObjectTarget?.folder_id === folder.id
                  }
                  onClick={() =>
                    moveObjectTarget &&
                    moveObjectMutation.mutate({
                      id: moveObjectTarget.id,
                      folderId: folder.id,
                    })
                  }
                >
                  {folder.name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Dialog>

      {/* Destructive confirmation opened from a row menu (owned by the page so
          the menu panel can unmount safely). */}
      <Dialog
        open={pendingConfirm !== null}
        title={pendingConfirm?.title ?? ""}
        onClose={() => setPendingConfirm(null)}
      >
        <div className="dialog-text">{pendingConfirm?.message}</div>
        {pendingConfirm?.folderCascade ? (
          <label className="cascade-option">
            <input
              type="checkbox"
              checked={folderDeleteWithContent}
              onChange={(event) => setFolderDeleteWithContent(event.target.checked)}
            />
            <span>Supprimer aussi tout son contenu (fichiers et sous-dossiers)</span>
          </label>
        ) : null}
        <div className="dialog-actions">
          <button
            type="button"
            className="btn"
            onClick={() => setPendingConfirm(null)}
          >
            Annuler
          </button>
          <button
            type="button"
            className={
              pendingConfirm?.danger ? "btn btn-danger" : "btn btn-primary"
            }
            onClick={() => {
              const action = pendingConfirm?.onConfirm;
              const withContent = folderDeleteWithContent;
              setPendingConfirm(null);
              action?.(withContent);
            }}
          >
            {pendingConfirm?.confirmLabel ?? "Confirmer"}
          </button>
        </div>
      </Dialog>

      {/* Bulk delete: opened by the selection bar or the Suppr shortcut. The
          dialog reports the real per-file progress instead of a mute spinner. */}
      <Dialog
        open={bulkDeleteOpen}
        title="Supprimer la sélection"
        onClose={() => setBulkDeleteOpen(false)}
      >
        <div className="dialog-text">
          Marquer{" "}
          <strong>
            {selectedIds.size === 1 ? "1 objet" : `${selectedIds.size} objets`}
          </strong>{" "}
          comme {selectedIds.size === 1 ? "supprimé" : "supprimés"} ?
          Chaque fichier est supprimé individuellement et le résultat est
          rapporté par fichier. Les octets restent jusqu'à une purge.
        </div>
        {deleteManyProgress ? (
          <>
            <div
              className="progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={deleteManyProgress.total}
              aria-valuenow={deleteManyProgress.done}
              aria-label="Progression de la suppression de la sélection"
            >
              <span
                className="progress-bar"
                style={{
                  width: `${
                    deleteManyProgress.total > 0
                      ? Math.round(
                          (deleteManyProgress.done / deleteManyProgress.total) * 100,
                        )
                      : 0
                  }%`,
                }}
              />
            </div>
            <p className="muted" role="status">
              Suppression {deleteManyProgress.done}/{deleteManyProgress.total}…
            </p>
          </>
        ) : null}
        <div className="dialog-actions">
          <button
            type="button"
            className="btn"
            disabled={deleteManyMutation.isPending}
            onClick={() => setBulkDeleteOpen(false)}
          >
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={
              deleteManyMutation.isPending || selectedIds.size === 0
            }
            onClick={() => deleteManyMutation.mutate([...selectedIds])}
          >
            {deleteManyMutation.isPending ? "Suppression…" : "Supprimer"}
          </button>
        </div>
      </Dialog>

      {/* Keyboard legend: opened with `?` or the header help button. */}
      <Dialog
        open={shortcutsOpen}
        title="Raccourcis clavier"
        onClose={() => setShortcutsOpen(false)}
      >
        <dl className="shortcut-list">
          <div>
            <dt>
              <kbd>/</kbd>
            </dt>
            <dd>Rechercher dans le dossier courant</dd>
          </div>
          <div>
            <dt>
              <kbd>Suppr</kbd>
            </dt>
            <dd>Supprimer la sélection (confirmation demandée)</dd>
          </div>
          <div>
            <dt>
              <kbd>?</kbd>
            </dt>
            <dd>Afficher cette légende</dd>
          </div>
          <div>
            <dt>
              <kbd>Échap</kbd>
            </dt>
            <dd>Fermer un menu, un panneau ou un dialogue</dd>
          </div>
        </dl>
        <p className="muted">
          Les raccourcis sont ignorés dans les champs de saisie.
        </p>
        <div className="dialog-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShortcutsOpen(false)}
          >
            Compris
          </button>
        </div>
      </Dialog>

      {queue.items.length > 0 ? (
        <UploadTray
          queue={queue}
          throughput={transfers.throughput}
          formatBytes={formatBytes}
          onClear={clearTray}
          onPause={pauseQueue}
          onResume={resumeQueue}
          onCancelItem={cancelQueueItem}
          onRetryItem={retryQueueItem}
        />

      ) : null}

      <MasterModeDialog
        open={masterDialogOpen}
        csrf={csrf}
        onClose={() => setMasterDialogOpen(false)}
      />
      <PreviewModal
        item={previewTarget}
        csrf={csrf}
        onClose={() => setPreviewTarget(null)}
        onDownload={(item) => {
          setPreviewTarget(null);
          void handleDownload(item);
        }}
      />
      <ShareDialog
        item={shareTarget}
        csrf={csrf}
        onClose={() => setShareTarget(null)}
        onNotify={notify}
      />
      <PacksDialog
        open={packsOpen}
        csrf={csrf}
        selectedIds={selectedIds}
        objects={items}
        onClose={() => setPacksOpen(false)}
        onNotify={notify}
      />
      <PublishDialog
        item={publishTarget}
        objects={items}
        csrf={csrf}
        onClose={() => setPublishTarget(null)}
        onChanged={() => {
          void queryClient.invalidateQueries({ queryKey: ["objects"] });
          void objectsQuery.refetch();
        }}
        onNotify={notify}
      />
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      {/* Recursive (cascade) folder deletion: real listing, typed confirmation,
          live progress, explicit per-item failure log. A native <dialog> so
          Escape/focus trapping are built in; Escape is routed to an explicit
          cancel while deleting instead of closing mid-run. */}
      {cascade ? (
        <dialog
          ref={cascadeDialogRef}
          className="dialog cascade-dialog"
          aria-labelledby="cascade-title"
          onCancel={(event) => {
            if (cascade.phase === "deleting") {
              event.preventDefault();
              cancelCascade();
            } else {
              closeCascade();
            }
          }}
        >
          <div className="dialog-head">
            <h2 id="cascade-title">Supprimer le dossier et son contenu</h2>
            {cascade.phase === "scanning" || cascade.phase === "confirm" ? (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                onClick={closeCascade}
                aria-label="Fermer"
              >
                Fermer
              </button>
            ) : null}
          </div>
          <div className="dialog-body">
            {cascade.phase === "scanning" ? (
              <p className="muted" role="status">
                Analyse du contenu réel du dossier…
              </p>
            ) : null}

            {cascade.phase === "confirm" ? (
              cascade.scanError ? (
                <p role="alert" className="alert alert-error">
                  {cascade.scanError}
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    onClick={() =>
                      void runCascadeScan(cascade.rootId, cascade.rootName)
                    }
                  >
                    Réessayer
                  </button>
                </p>
              ) : cascade.plan ? (
                <>
                  <p className="dialog-text">
                    Le dossier <strong>{cascade.rootName}</strong> contient{" "}
                    <strong>{cascade.plan.fileCount} fichier(s)</strong> et{" "}
                    <strong>{cascade.plan.folderCount} sous-dossier(s)</strong>.
                  </p>
                  <p role="alert" className="alert alert-error">
                    Suppression du contenu : chaque fichier est marqué supprimé
                    (les octets restent jusqu'à une purge), puis chaque dossier
                    vidé est supprimé, des feuilles vers la racine.
                  </p>
                  <label className="field cascade-confirm-field">
                    <span>Recopiez «&nbsp;{cascade.rootName}&nbsp;» pour confirmer</span>
                    <input
                      type="text"
                      value={cascadeConfirmText}
                      onChange={(event) =>
                        setCascadeConfirmText(event.target.value)
                      }
                      autoFocus
                      aria-label="Confirmation par recopie du nom"
                    />
                  </label>
                  <div className="dialog-actions">
                    <button type="button" className="btn" onClick={closeCascade}>
                      Annuler
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger"
                      disabled={!cascadeConfirmed}
                      onClick={startCascade}
                    >
                      Supprimer le contenu et le dossier
                    </button>
                  </div>
                </>
              ) : null
            ) : null}

            {cascade.phase === "deleting" || cascade.phase === "done" ? (
              <>
                <p
                  role="status"
                  className={
                    cascade.phase === "done" &&
                    !cascade.cancelled &&
                    cascade.failures.length === 0
                      ? "alert alert-ok"
                      : "dialog-text cascade-progress-text"
                  }
                >
                  {cascade.phase === "deleting"
                    ? `Suppression en cours — ${cascade.done}/${cascade.ops.length}`
                    : cascade.cancelled
                      ? `Suppression interrompue — ${cascade.done}/${cascade.ops.length}`
                      : cascade.failures.length === 0
                        ? `Contenu supprimé et dossier supprimé — ${cascade.done}/${cascade.ops.length}`
                        : `Suppression terminée avec échecs — ${cascade.done}/${cascade.ops.length}`}
                </p>
                <div
                  className="progress"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={cascade.ops.length}
                  aria-valuenow={cascade.done}
                  aria-label="Progression de la suppression récursive"
                >
                  <span
                    className="progress-bar"
                    style={{
                      width: `${
                        cascade.ops.length > 0
                          ? Math.round((cascade.done / cascade.ops.length) * 100)
                          : 0
                      }%`,
                    }}
                  />
                </div>
                {cascade.phase === "deleting" && cascade.current ? (
                  <p className="muted">Traitement : {cascade.current}</p>
                ) : null}

                {cascade.failures.length > 0 ? (
                  <div className="cascade-log">
                    <h3 className="cascade-log-title">
                      Journal des échecs ({cascade.failures.length})
                    </h3>
                    <ul className="cascade-log-list">
                      {cascade.failures.map((failure) => (
                        <li key={failure.key} className="cascade-log-item">
                          <span
                            className={`chip ${
                              failure.kind === "folder" ? "chip-warn" : "chip-error"
                            }`}
                          >
                            {failure.kind === "folder" ? "Dossier" : "Fichier"}
                          </span>
                          <span className="cascade-log-name">{failure.label}</span>
                          <span className="muted cascade-log-path">
                            {failure.path}
                          </span>
                          <span className="muted cascade-log-error">
                            {failure.error}
                          </span>
                          {cascade.phase === "done" ? (
                            <span className="cascade-log-actions">
                              <button
                                type="button"
                                className="btn btn-ghost btn-small"
                                onClick={() => retryCascadeItem(failure)}
                              >
                                Réessayer
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-small"
                                onClick={() => abandonCascadeItem(failure)}
                              >
                                Abandonner
                              </button>
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="dialog-actions">
                  {cascade.phase === "deleting" ? (
                    <button type="button" className="btn" onClick={cancelCascade}>
                      Annuler
                    </button>
                  ) : (
                    <>
                      {cascade.failures.length > 0 ? (
                        <button
                          type="button"
                          className="btn"
                          onClick={retryCascadeFailures}
                        >
                          Réessayer les échecs
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={closeCascade}
                      >
                        Fermer
                      </button>
                    </>
                  )}
                </div>
              </>
            ) : null}
          </div>
        </dialog>
      ) : null}
    </div>
  );
}
