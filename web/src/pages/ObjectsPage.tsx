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
import { idleTransfer, runTransfer } from "../lib/transfer";
import type { TransferDeps, TransferPhase, TransferState } from "../lib/transfer";
import { useAuth, useSession } from "../lib/auth";
import { ConfirmAction, Dialog } from "../components/Dialog";
import { FolderMark } from "../components/FolderMark";
import { RowMenu } from "../components/RowMenu";

/** Objects fetched per page ("Charger plus" increments the offset). */
const OBJECTS_PAGE_SIZE = 50;

/** Human label for each transfer phase (import → validation → availability). */
const PHASE_LABEL: Record<TransferPhase, string> = {
  idle: "Prêt",
  "requesting-intent": "Autorisation…",
  uploading: "Envoi…",
  validating: "Validation…",
  available: "Disponible",
  failed: "Échec",
  cancelled: "Annulé",
};

/** One idempotency key per user submission; automatic retries reuse it. */
function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Tous les états" },
  { value: "available", label: "Disponible" },
  { value: "pending", label: "En cours" },
  { value: "deleted", label: "Supprimé" },
  { value: "expired", label: "Expiré" },
  { value: "failed", label: "Échec" },
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
  const [file, setFile] = useState<File | null>(null);
  // Upload runs through the M03 transfer engine (progress, retries, cancel).
  const [transfer, setTransfer] = useState<TransferState>(() => idleTransfer(null));
  const uploadController = useRef<AbortController | null>(null);
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

  /** True while a submission is in flight (blocks accidental double submit). */
  const transferActive =
    transfer.phase === "requesting-intent" ||
    transfer.phase === "uploading" ||
    transfer.phase === "validating";

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

  // -- handlers ------------------------------------------------------------
  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    setUploadError(null);
    if (!file) {
      setUploadError("Choisissez d'abord un fichier.");
      return;
    }
    if (transferActive) {
      // Block an accidental second submission while one is in flight.
      return;
    }
    if (!csrf) {
      setUploadError("Session expirée. Reconnectez-vous.");
      return;
    }
    const controller = new AbortController();
    uploadController.current = controller;
    setTransfer({ ...idleTransfer(file), phase: "requesting-intent" });
    try {
      const result = await runTransfer(file, transferDeps(csrf), {
        folderId: currentFolderId,
        idempotencyKey: newIdempotencyKey(),
        signal: controller.signal,
        onUpdate: setTransfer,
      });
      if (result.state.phase === "available") {
        // Only the backend commit sets this phase, so success is never faked.
        // The engine's inline status shows the confirmation; no second banner.
        setFile(null);
        setUploadError(null);
        invalidateLibrary();
      } else if (result.state.phase === "failed") {
        setNotice(null);
        setUploadError(result.state.error ?? "Envoi impossible.");
      }
      // "cancelled": keep the chosen file, surface no error.
    } finally {
      uploadController.current = null;
    }
  }

  function handleCancelUpload() {
    uploadController.current?.abort();
  }

  function handleFileChange(selected: File | null) {
    setFile(selected);
    setUploadError(null);
    setTransfer(idleTransfer(selected));
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
  const currentName = currentFolderId ? byId.get(currentFolderId)?.name : null;

  const moveBlocked = moveTarget ? forbiddenTargets(moveTarget.id) : new Set<string>();
  const deletePendingId = deleteObjectMutation.isPending
    ? deleteObjectMutation.variables
    : undefined;
  const purgePendingId = purgeMutation.isPending ? purgeMutation.variables : undefined;
  const objectBusy =
    deleteObjectMutation.isPending ||
    purgeMutation.isPending ||
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
            className="btn btn-primary"
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
      </aside>

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
          <div className="ledger" role="list">
            <div className="ledger-head" aria-hidden="true">
              <span>Nom</span>
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
                downloadingId === item.id;
              return (
                <div className="ledger-row" role="listitem" key={item.id}>
                  <div className="ledger-name">
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

      <section className="card intake" aria-labelledby="upload-title">
        <h2 id="upload-title">Importer{currentName ? ` dans « ${currentName} »` : ""}</h2>
        <p className="muted">
          Le fichier est déposé, puis vérifié par empreinte SHA-256 avant d'être
          déclaré disponible.
        </p>
        <form onSubmit={handleUpload} className="form form-inline">
          <div className="field file-field">
            <span>Fichier</span>
            <label className="file-picker">
              <input
                type="file"
                name="file"
                className="visually-hidden"
                disabled={transferActive}
                onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
              />
              <span className="btn">Choisir un fichier…</span>
              <span className="file-picker-name">
                {file ? file.name : "Aucun fichier sélectionné"}
              </span>
            </label>
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={transferActive || !file}
          >
            {transferActive ? "Transfert…" : "Importer et valider"}
          </button>
          {transferActive ? (
            <button type="button" className="btn" onClick={handleCancelUpload}>
              Annuler
            </button>
          ) : null}
        </form>

        {transfer.phase !== "idle" ? (
          <div className="transfer" data-testid="transfer-status" aria-live="polite">
            <div className="transfer-head">
              <span className="transfer-name">{transfer.fileName}</span>
              <span className="muted">{formatBytes(transfer.sizeBytes)}</span>
              <span
                className={
                  transfer.phase === "available"
                    ? "chip chip-ok"
                    : transfer.phase === "failed"
                      ? "chip chip-error"
                      : transfer.phase === "cancelled"
                        ? "chip chip-muted"
                        : "chip chip-warn"
                }
              >
                {PHASE_LABEL[transfer.phase]}
              </span>
            </div>
            {transfer.phase === "uploading" ? (
              <div
                className="progress"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(transfer.progress * 100)}
                aria-label="Progression du transfert"
              >
                <span
                  className="progress-bar"
                  style={{ width: `${Math.round(transfer.progress * 100)}%` }}
                />
              </div>
            ) : null}
            {transfer.attempts > 0 ? (
              <p className="muted">
                Tentatives : {transfer.attempts} — temporisation avec jitter.
              </p>
            ) : null}
          </div>
        ) : null}

        {uploadError ? (
          <p role="alert" className="alert alert-error">
            {uploadError}
          </p>
        ) : null}
        {transfer.phase === "available" ? (
          <p role="status" className="alert alert-ok">
            Import validé et vérifié par le backend.
          </p>
        ) : null}
        {transfer.phase === "cancelled" ? (
          <p role="status" className="alert">
            Import annulé.
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
            <dd className="mono">
              {details.checksum_sha256 ? details.checksum_sha256 : "non disponible"}
            </dd>
          </dl>
          <div className="drawer-actions">
            <button
              type="button"
              className="btn"
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
              className="btn"
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
                className="btn btn-danger"
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
