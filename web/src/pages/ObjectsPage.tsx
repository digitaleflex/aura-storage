import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ApiError, api, hasScope, putToPresignedUrl } from "../lib/api";
import type { FolderItem, ObjectItem, ObjectQuery } from "../lib/api";
import { emptyQueue, startUploadQueue } from "../lib/transfer";
import type {
  QueueInput,
  QueueState,
  TransferDeps,
  TransferPhase,
  UploadQueue,
} from "../lib/transfer";
import {
  MAX_UPLOAD_DEPTH,
  normalizeRelativePath,
  parentDirOf,
  planFolders,
} from "../lib/folderTree";
import { useAuth, useSession } from "../lib/auth";
import { ConfirmAction, Dialog } from "../components/Dialog";
import { FolderMark } from "../components/FolderMark";
import { RowMenu } from "../components/RowMenu";

/** Objects fetched per page ("Charger plus" increments the offset). */
const OBJECTS_PAGE_SIZE = 50;

/** Human label for each transfer phase (import → validation → availability). */
const PHASE_LABEL: Record<TransferPhase, string> = {
  idle: "En attente",
  "requesting-intent": "Autorisation…",
  uploading: "Envoi…",
  validating: "Validation…",
  available: "Disponible",
  failed: "Échec",
  cancelled: "Annulé",
};

/** Phases that are still moving (offer a per-file interrupt). */
const ACTIVE_PHASES: TransferPhase[] = ["requesting-intent", "uploading", "validating"];

/** Chip style for a queue item's phase. */
function queuePhaseClass(phase: TransferPhase): string {
  if (phase === "available") return "chip chip-ok";
  if (phase === "failed") return "chip chip-error";
  if (phase === "cancelled" || phase === "idle") return "chip chip-muted";
  return "chip chip-warn";
}

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Tous les états" },
  { value: "available", label: "Disponible" },
  { value: "pending", label: "En cours" },
  { value: "deleted", label: "Supprimé" },
  { value: "expired", label: "Expiré" },
  { value: "failed", label: "Échec" },
  { value: "aborted", label: "Abandonné" },
];

const SORT_OPTIONS: {
  value: NonNullable<ObjectQuery["sort"]>;
  label: string;
}[] = [
  { value: "created_at", label: "Date" },
  { value: "display_name", label: "Nom" },
  { value: "size_bytes", label: "Taille" },
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
  deleted: "Supprimé",
  expired: "Expiré",
  failed: "Échec",
  aborted: "Abandonné",
};

/** Friendly type label for scanning; the raw MIME stays in the details panel. */
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
  if (value === "application/json") return "JSON";
  if (value === "text/csv") return "CSV";
  if (value.startsWith("text/")) return "Texte";
  if (value === "application/octet-stream") return "Binaire";
  return contentType.split("/")[1] ?? contentType;
}

/** Status shown as a dot plus a word, so it never relies on colour alone. */
function StatusLabel({ status }: { status: string }) {
  const variant =
    status === "available"
      ? "status status-ok"
      : status === "pending"
        ? "status status-warn"
        : status === "failed"
          ? "status status-error"
          : "status";
  return <span className={variant}>{STATUS_LABELS[status] ?? status}</span>;
}

/** The whole folder tree is fetched in one request (`?all=true`); the hierarchy
 * is rebuilt client-side from parent_id for breadcrumbs and the move pickers. */
export function ObjectsPage() {
  const { csrf } = useAuth();
  const session = useSession();
  const queryClient = useQueryClient();

  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  // Uploads run through the M03 transfer engine as a bounded multi-file queue.
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [queue, setQueue] = useState<QueueState>(() => emptyQueue());
  const queueRef = useRef<UploadQueue | null>(null);
  const dirInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [renameTarget, setRenameTarget] = useState<FolderItem | null>(null);
  const [renameName, setRenameName] = useState("");
  const [moveTarget, setMoveTarget] = useState<FolderItem | null>(null);
  const [moveObjectTarget, setMoveObjectTarget] = useState<ObjectItem | null>(null);
  const [details, setDetails] = useState<ObjectItem | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<{
    title: string;
    message: ReactNode;
    confirmLabel: string;
    danger?: boolean;
    onConfirm: () => void;
  } | null>(null);

  // -- search / filter / sort (server-side; M02) ---------------------------
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [minSize, setMinSize] = useState("");
  const [maxSize, setMaxSize] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [sortField, setSortField] = useState<NonNullable<ObjectQuery["sort"]>>(
    "created_at",
  );
  const [sortOrder, setSortOrder] = useState<NonNullable<ObjectQuery["order"]>>("desc");

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
  }

  const canPurge = hasScope(session.data?.scopes, "objects:purge");

  /** True while any file of the queue is transferring (blocks double submit). */
  const transferActive = queue.active > 0;

  /** Wire the injected engine to the real API for one authenticated session. */
  function transferDeps(activeCsrf: string): TransferDeps {
    return {
      requestIntent: (input) =>
        api.createUploadIntent(
          {
            display_name: input.fileName,
            content_type: input.contentType,
            size_bytes: input.sizeBytes,
            folder_id: input.folderId,
          },
          activeCsrf,
          { idempotencyKey: input.idempotencyKey },
        ),
      upload: (url, selected, opts) =>
        putToPresignedUrl(url, selected, {
          headers: opts.headers,
          onProgress: opts.onProgress,
          signal: opts.signal,
        }),
      commit: (id) => api.commitObject(id, activeCsrf),
      abortIntent: async (id) => {
        await api.abortObject(id, activeCsrf);
      },
      sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
      random: Math.random,
    };
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

  const tree = treeQuery.data?.items ?? [];
  const byId = useMemo(() => new Map(tree.map((f) => [f.id, f])), [tree]);
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
    setActionError(err instanceof ApiError ? err.detail : fallback);
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

  const deleteFolderMutation = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.deleteFolder(id, csrf);
    },
    onSuccess: (_data, id) => {
      if (currentFolderId === id) setCurrentFolderId(null);
      setNotice("Dossier supprimé.");
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Suppression du dossier impossible."),
  });

  // Delete is confirmed against the server: the row is only refreshed (never
  // removed locally) once the API reports success.
  const deleteObjectMutation = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.deleteObject(id, csrf);
    },
    onSuccess: () => {
      setDetails(null);
      setNotice("Objet marqué comme supprimé. Les octets restent jusqu'à une purge.");
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
      for (const id of ids) {
        try {
          await api.deleteObject(id, csrf);
          deleted += 1;
        } catch {
          const target = items.find((item) => item.id === id);
          failed.push(target?.display_name ?? id);
        }
      }
      return { deleted, failed };
    },
    onSuccess: ({ deleted, failed }) => {
      setSelectedIds(new Set());
      setDetails(null);
      if (failed.length === 0) {
        setNotice(
          `${deleted} objet(s) marqué(s) comme supprimé(s). Les octets restent jusqu'à une purge.`,
        );
      } else {
        // Per-file outcome matters here: ApiError carries only one detail,
        // so the summary is set explicitly instead of via reportError.
        setNotice(null);
        setActionError(
          `${deleted} supprimé(s), ${failed.length} échec(s) : ${failed.slice(0, 5).join(", ")}${failed.length > 5 ? "…" : ""}`,
        );
      }
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Suppression en masse impossible."),
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
    setQueue(next);
    if (!next.finished) return;
    if (next.done > 0) invalidateLibrary();
    if (next.failed > 0) {
      const firstFailed = next.items.find((item) => item.state.phase === "failed");
      setUploadError(firstFailed?.state.error ?? "Envoi impossible.");
    } else {
      setUploadError(null);
    }
    setPendingFiles([]);
  }

  function handleUpload(event: FormEvent) {
    event.preventDefault();
    setUploadError(null);
    setNotice(null);
    if (pendingFiles.length === 0) {
      setUploadError("Choisissez au moins un fichier.");
      return;
    }
    if (transferActive) {
      // Block an accidental second submission while files are in flight.
      return;
    }
    if (!csrf) {
      setUploadError("Session expirée. Reconnectez-vous.");
      return;
    }
    const uploadQueue = startUploadQueue(pendingFiles, transferDeps(csrf), {
      folderId: currentFolderId,
      onUpdate: handleQueueUpdate,
    });
    queueRef.current = uploadQueue;
  }

  /** Directory import (#64): recreate the missing folders, then upload in place. */
  async function handleFolderUpload(selected: FileList | null) {
    if (!selected || selected.length === 0) return;
    if (!csrf) {
      setUploadError("Session expirée. Reconnectez-vous.");
      return;
    }
    if (transferActive) return;
    setUploadError(null);
    setNotice(null);

    const list = Array.from(selected);
    const relPaths = list.map((file) =>
      normalizeRelativePath(
        (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
      ),
    );
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

    let createdAny = false;
    for (const folder of plan.folders) {
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
        }
        setUploadError("Création de l'arborescence impossible.");
        return;
      }
    }
    if (createdAny) invalidateLibrary();
    if (plan.tooDeep.length > 0) {
      setNotice(
        `${plan.tooDeep.length} fichier(s) ignoré(s) : arborescence trop profonde (max ${MAX_UPLOAD_DEPTH}).`,
      );
    }

    const entries: QueueInput[] = kept.map((item) => {
      const dir = parentDirOf(item.rel);
      return {
        file: item.file,
        folderId: dir ? (folderIds.get(dir) ?? currentFolderId) : currentFolderId,
      };
    });
    const uploadQueue = startUploadQueue(entries, transferDeps(csrf), {
      folderId: currentFolderId,
      onUpdate: handleQueueUpdate,
    });
    queueRef.current = uploadQueue;
  }

  function handleCancelUpload() {
    queueRef.current?.cancelAll();
  }

  function handleRetryFailed() {
    setUploadError(null);
    queueRef.current?.retryFailed();
  }

  function handleFilesChange(selected: FileList | File[] | null) {
    const list = selected ? Array.from(selected) : [];
    if (list.length === 0) return;
    setUploadError(null);
    setPendingFiles((current) => [...current, ...list]);
  }

  function removePendingFile(index: number) {
    setPendingFiles((current) => current.filter((_, i) => i !== index));
  }

  async function handleDownload(item: ObjectItem) {
    setActionError(null);
    setDownloadStatus(null);
    if (!csrf) {
      setActionError("Session expirée. Reconnectez-vous.");
      return;
    }
    setDownloadingId(item.id);
    try {
      const intent = await api.createDownloadIntent(item.id, csrf);
      // The browser performs the direct S3 GET; it manages its own progress.
      window.open(intent.download_url, "_blank", "noopener");
      setDownloadStatus(
        `Téléchargement de « ${intent.display_name} » lancé (${formatBytes(
          intent.size_bytes,
        )}).`,
      );
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? `Téléchargement refusé : ${err.detail}`
          : "Téléchargement impossible.",
      );
    } finally {
      setDownloadingId(null);
    }
  }

  async function handleCopyReference(item: ObjectItem) {
    setActionError(null);
    try {
      await navigator.clipboard.writeText(item.id);
      setNotice(`Référence copiée : ${item.id}`);
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

  const items = objectsQuery.data?.pages.flatMap((page) => page.items) ?? [];

  // Only deletable rows are selectable: the server refuses anything else
  // with 409, so offering them would manufacture failures.
  const selectableItems = items.filter(
    (item) => item.status === "available" || item.status === "pending",
  );
  const selectableIds = new Set(selectableItems.map((item) => item.id));

  // Real weight of what is currently loaded — shown as a rail readout, so the
  // casiers column carries information instead of empty graphite.
  const loadedBytes = items.reduce(
    (sum, item) => sum + (item.size_bytes > 0 ? item.size_bytes : 0),
    0,
  );
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
    abortUploadMutation.isPending ||
    moveObjectMutation.isPending ||
    downloadingId !== null;

  return (
    <div className="stack vault-workspace">
      <div className="page-head">
        <h1>Fichiers</h1>
        <div className="head-actions">
          <button
            type="button"
            className="btn"
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
            className="btn"
            onClick={() => {
              setNewFolderName("");
              setNewFolderOpen(true);
            }}
          >
            Nouveau dossier
          </button>
        </div>
      </div>

      {currentFolderId !== null ? (
        <nav className="breadcrumb" aria-label="Fil d'Ariane">
        <button
          type="button"
          className={currentFolderId === null ? "crumb crumb-current" : "crumb"}
          aria-current={currentFolderId === null ? "page" : undefined}
          onClick={() => setCurrentFolderId(null)}
        >
          Racine
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
      ) : null}

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

      <aside className="casiers" aria-labelledby="folders-title">
        <h2 id="folders-title">Dossiers</h2>
        <ul className="casier-list">
          <li
            className={
              currentFolderId === null ? "casier casier-current" : "casier"
            }
          >
            <button
              type="button"
              className="folder-open"
              aria-current={currentFolderId === null ? "true" : undefined}
              onClick={() => setCurrentFolderId(null)}
            >
              <span className="folder-icon" aria-hidden="true">
                <FolderMark />
              </span>
              <span className="folder-name">Racine</span>
            </button>
          </li>
        </ul>
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
        ) : treeQuery.isPending ? (
          <p className="muted">Chargement…</p>
        ) : subfolders.length === 0 ? (
          <p className="empty">Aucun sous-dossier ici.</p>
        ) : (
          <ul className="casier-list">
            {subfolders.map((folder) => (
              <li key={folder.id} className="casier">
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
                <RowMenu
                  label={`Actions pour le dossier ${folder.name}`}
                  items={[
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
                      onSelect: () =>
                        setPendingConfirm({
                          title: "Supprimer le dossier",
                          message: (
                            <>
                              Supprimer <strong>{folder.name}</strong> ? Un dossier
                              non vide est refusé.
                            </>
                          ),
                          confirmLabel: "Supprimer",
                          danger: true,
                          onConfirm: () => deleteFolderMutation.mutate(folder.id),
                        }),
                    },
                  ]}
                />
              </li>
            ))}
          </ul>
        )}
        <div className="casiers-foot">
          <dl>
            <dt>Position</dt>
            <dd>{currentName ?? "Racine"}</dd>
            <dt>Poids affiché</dt>
            <dd className="num">{formatBytes(loadedBytes)}</dd>
          </dl>
        </div>
      </aside>

      <section
        className="card intake"
        aria-labelledby="upload-title"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (!transferActive) handleFilesChange(e.dataTransfer.files);
        }}
      >
        <h2 id="upload-title">
          Importer{currentName ? ` dans « ${currentName} »` : ""}
        </h2>
        <p className="muted">
          Déposez des fichiers ici ou choisissez-les. Chaque fichier est vérifié
          par empreinte SHA-256 avant d'être déclaré disponible.
        </p>
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
            disabled={transferActive || pendingFiles.length === 0}
          >
            {transferActive ? "Transfert…" : "Importer et valider"}
          </button>
          {transferActive ? (
            <button type="button" className="btn" onClick={handleCancelUpload}>
              Annuler
            </button>
          ) : null}
          {!transferActive && (queue.failed > 0 || queue.cancelled > 0) ? (
            <button type="button" className="btn" onClick={handleRetryFailed}>
              Réessayer les échecs
            </button>
          ) : null}
        </form>

        {pendingFiles.length > 0 && !transferActive ? (
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
        ) : null}

        {queue.items.length > 0 ? (
          <div className="transfer" data-testid="transfer-status" aria-live="polite">
            <div className="queue-head">
              <span className="muted">
                {queue.done}/{queue.items.length} transféré
                {queue.items.length > 1 ? "s" : ""}
                {queue.failed > 0 ? ` · ${queue.failed} en échec` : ""}
                {queue.cancelled > 0
                  ? ` · ${queue.cancelled} annulé${queue.cancelled > 1 ? "s" : ""}`
                  : ""}
              </span>
              {transferActive ? (
                <span className="muted">
                  jusqu'à {queue.concurrency} en parallèle
                </span>
              ) : null}
            </div>
            {transferActive &&
            queue.maxConcurrency > 1 &&
            queue.concurrency < queue.maxConcurrency ? (
              <p className="muted" role="status">
                Connexion difficile : envois limités à {queue.concurrency} à la
                fois — retour à {queue.maxConcurrency} dès que ça passe.
              </p>
            ) : null}
            <ul className="queue">
              {queue.items.map((item) => (
                <li key={item.id} className="queue-item">
                  <div className="queue-line">
                    <span className="transfer-name">{item.fileName}</span>
                    <span className="muted">{formatBytes(item.sizeBytes)}</span>
                    <span className={queuePhaseClass(item.state.phase)}>
                      {PHASE_LABEL[item.state.phase]}
                    </span>
                    {ACTIVE_PHASES.includes(item.state.phase) ? (
                      <button
                        type="button"
                        className="btn btn-ghost btn-small"
                        aria-label={`Interrompre ${item.fileName}`}
                        onClick={() => queueRef.current?.cancelItem(item.id)}
                      >
                        ×
                      </button>
                    ) : null}
                    {item.state.phase === "failed" ||
                    item.state.phase === "cancelled" ? (
                      <button
                        type="button"
                        className="btn btn-ghost btn-small"
                        aria-label={`Relancer ${item.fileName}`}
                        onClick={() => {
                          setUploadError(null);
                          queueRef.current?.retryItem(item.id);
                        }}
                      >
                        Relancer
                      </button>
                    ) : null}
                  </div>
                  {item.state.phase === "uploading" ? (
                    <div
                      className="progress"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(item.state.progress * 100)}
                      aria-label={`Progression de ${item.fileName}`}
                    >
                      <span
                        className="progress-bar"
                        style={{ width: `${Math.round(item.state.progress * 100)}%` }}
                      />
                    </div>
                  ) : null}
                  {item.state.phase === "uploading" ? (
                    <p className="muted">
                      {formatBytes(item.state.transferredBytes)} /{" "}
                      {formatBytes(item.state.sizeBytes)} (
                      {Math.round(item.state.progress * 100)} %)
                    </p>
                  ) : null}
                  {item.state.attempts > 0 &&
                  ACTIVE_PHASES.includes(item.state.phase) ? (
                    <p className="muted">
                      Nouvelle tentative ({item.state.attempts})…
                    </p>
                  ) : null}
                  {item.state.error && item.state.phase === "failed" ? (
                    <p className="muted">{item.state.error}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
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
          <h2 id="objects-title">
            Objets{currentName ? ` — ${currentName}` : " — racine"}
          </h2>
          <span className="muted" aria-live="polite">
            {items.length} objet{items.length > 1 ? "s" : ""} affiché
            {items.length > 1 ? "s" : ""}
            {objectsQuery.hasNextPage ? " (d'autres restent à charger)" : ""}
          </span>
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
          <label className="field">
            <span>Trier par</span>
            <select
              name="sort"
              value={sortField}
              onChange={(e) =>
                setSortField(e.target.value as NonNullable<ObjectQuery["sort"]>)
              }
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Ordre</span>
            <select
              name="order"
              value={sortOrder}
              onChange={(e) =>
                setSortOrder(e.target.value as NonNullable<ObjectQuery["order"]>)
              }
            >
              <option value="desc">Décroissant</option>
              <option value="asc">Croissant</option>
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
          <p className="muted">Chargement du catalogue…</p>
        ) : items.length === 0 ? (
          <p className="empty">
            {hasActiveFilters
              ? "Aucun fichier ne correspond à ces critères."
              : "Aucun fichier dans ce dossier."}
          </p>
        ) : (
          <>
            {selectedIds.size > 0 ? (
              <p role="status" className="alert">
                {selectedIds.size} objet(s) sélectionné(s).{" "}
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  disabled={deleteManyMutation.isPending}
                  onClick={() => setSelectedIds(new Set())}
                >
                  Tout désélectionner
                </button>{" "}
                <ConfirmAction
                  label={
                    deleteManyMutation.isPending
                      ? "Suppression…"
                      : "Supprimer la sélection"
                  }
                  title="Supprimer la sélection"
                  message={
                    <>
                      Marquer <strong>{selectedIds.size} objet(s)</strong>{" "}
                      comme supprimé(s) ? Chaque fichier est supprimé
                      individuellement et le résultat est rapporté par
                      fichier. Les octets restent jusqu'à une purge.
                    </>
                  }
                  confirmLabel="Supprimer"
                  danger
                  pending={deleteManyMutation.isPending}
                  onConfirm={() =>
                    deleteManyMutation.mutate([...selectedIds])
                  }
                />
              </p>
            ) : null}
            <div className="ledger" role="list">
            <div className="ledger-head" aria-hidden="true">
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
                Nom
              </span>
              <span>Type</span>
              <span>Taille</span>
              <span>État</span>
              <span>Modifié</span>
              <span />
            </div>
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
                      {formatDateTime(item.updated_at)}
                    </span>
                  </div>
                  <div className="ledger-menu">
                    <RowMenu
                      label={`Actions pour ${item.display_name}`}
                      items={[
                        { label: "Détails", onSelect: () => setDetails(item) },
                        {
                          label: "Télécharger",
                          disabled:
                            item.status !== "available" || downloadingId !== null,
                          onSelect: () => void handleDownload(item),
                        },
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
                        {
                          label: "Supprimer",
                          danger: true,
                          disabled: objectBusy,
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
                                onSelect: () =>
                                  setPendingConfirm({
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
          <div className="load-more">
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
        {downloadStatus ? (
          <p role="status" className="alert alert-ok">
            {downloadStatus}
          </p>
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
          onKeyDown={(e) => {
            if (e.key === "Escape") setDetails(null);
          }}
        >
          <div className="drawer-head">
            <h2 id="details-title">{details.display_name}</h2>
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => setDetails(null)}
              aria-label="Fermer les détails"
            >
              Fermer
            </button>
          </div>
          <dl className="detail-list">
            <dt>Nom</dt>
            <dd>{details.display_name}</dd>
            <dt>Identifiant</dt>
            <dd className="mono">{details.id}</dd>
            <dt>Type MIME</dt>
            <dd>{details.content_type}</dd>
            <dt>Taille</dt>
            <dd>
              {formatBytes(details.size_bytes)}
              <span className="muted"> ({details.size_bytes} octets)</span>
            </dd>
            <dt>État</dt>
            <dd>
              <StatusLabel status={details.status} />
            </dd>
            <dt>Dossier</dt>
            <dd>{folderPath(details.folder_id)}</dd>
            <dt>Créé le</dt>
            <dd>{formatDateTime(details.created_at)}</dd>
            <dt>Modifié le</dt>
            <dd>{formatDateTime(details.updated_at)}</dd>
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
                        setNotice("Copie impossible : contexte non sécurisé.");
                        return;
                      }
                      void navigator.clipboard.writeText(value).then(
                        () => setNotice("Empreinte SHA-256 copiée."),
                        () => setNotice("Copie refusée par le navigateur."),
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
          </dl>
          <div className="drawer-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={details.status !== "available" || downloadingId !== null}
              onClick={() => void handleDownload(details)}
            >
              {downloadingId === details.id ? "…" : "Télécharger"}
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => void handleCopyReference(details)}
            >
              Copier la référence
            </button>
            <button
              type="button"
              className="btn"
              disabled={objectBusy}
              onClick={() => setMoveObjectTarget(details)}
            >
              Déplacer
            </button>
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
              className="btn drawer-actions-danger"
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
              setPendingConfirm(null);
              action?.();
            }}
          >
            {pendingConfirm?.confirmLabel ?? "Confirmer"}
          </button>
        </div>
      </Dialog>
    </div>
  );
}
