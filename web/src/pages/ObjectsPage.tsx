import { useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ApiError, api, hasScope, putToPresignedUrl } from "../lib/api";
import type { FolderItem, ObjectItem } from "../lib/api";
import { idleTransfer, runTransfer } from "../lib/transfer";
import type { TransferDeps, TransferPhase, TransferState } from "../lib/transfer";
import { useAuth, useSession } from "../lib/auth";
import { ConfirmAction, Dialog } from "../components/Dialog";
import { FolderMark } from "../components/FolderMark";

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

function statusChip(status: string) {
  if (status === "available") {
    return <span className="chip chip-ok">Disponible</span>;
  }
  if (status === "pending") {
    return <span className="chip chip-warn">En cours</span>;
  }
  return <span className="chip chip-muted">{status}</span>;
}

/** The whole folder tree is fetched in one request (`?all=true`); the hierarchy
 * is rebuilt client-side from parent_id for breadcrumbs and the move pickers. */
export function ObjectsPage() {
  const { csrf } = useAuth();
  const session = useSession();
  const queryClient = useQueryClient();

  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [transfer, setTransfer] = useState<TransferState>(() => idleTransfer(null));
  const uploadController = useRef<AbortController | null>(null);
  const [filter, setFilter] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [renameTarget, setRenameTarget] = useState<FolderItem | null>(null);
  const [renameName, setRenameName] = useState("");
  const [moveTarget, setMoveTarget] = useState<FolderItem | null>(null);
  const [moveObjectTarget, setMoveObjectTarget] = useState<ObjectItem | null>(null);

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
    queryKey: ["objects", currentFolderId],
    queryFn: ({ pageParam }) =>
      api.listObjects(currentFolderId, {
        limit: OBJECTS_PAGE_SIZE,
        offset: pageParam,
      }),
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

  function invalidateLibrary() {
    void queryClient.invalidateQueries({ queryKey: ["objects"] });
    void queryClient.invalidateQueries({ queryKey: ["folders"] });
  }

  function reportError(err: unknown, fallback: string) {
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
      invalidateLibrary();
    },
    onError: (err) => reportError(err, "Suppression du dossier impossible."),
  });

  const deleteObjectMutation = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.deleteObject(id, csrf);
    },
    onSuccess: invalidateLibrary,
    onError: (err) => reportError(err, "Suppression impossible."),
  });

  const purgeMutation = useMutation({
    mutationFn: (id: string) => {
      if (!csrf) throw new Error("Session expirée.");
      return api.purgeObject(id, csrf);
    },
    onSuccess: invalidateLibrary,
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
        setFile(null);
        setUploadError(null);
        invalidateLibrary();
      } else if (result.state.phase === "failed") {
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
    setDownloadError(null);
    setDownloadStatus(null);
    if (!csrf) {
      setDownloadError("Session expirée. Reconnectez-vous.");
      return;
    }
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
      setDownloadError(
        err instanceof ApiError
          ? `Téléchargement refusé : ${err.detail}`
          : "Téléchargement impossible.",
      );
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
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? items.filter((item) => item.display_name.toLowerCase().includes(needle))
    : items;
  const currentName = currentFolderId ? byId.get(currentFolderId)?.name : null;

  const moveBlocked = moveTarget ? forbiddenTargets(moveTarget.id) : new Set<string>();

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Fichiers</h1>
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

      <section className="section" aria-labelledby="folders-title">
        <h2 id="folders-title">Dossiers</h2>
        {treeQuery.isError ? (
          <p role="alert" className="alert alert-error">
            Dossiers indisponibles.
          </p>
        ) : treeQuery.isPending ? (
          <p className="muted">Chargement…</p>
        ) : subfolders.length === 0 ? (
          <p className="empty">Aucun sous-dossier ici.</p>
        ) : (
          <ul className="folder-grid">
            {subfolders.map((folder) => (
              <li key={folder.id} className="folder-card">
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
                <div className="folder-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    onClick={() => {
                      setRenameName(folder.name);
                      setRenameTarget(folder);
                    }}
                  >
                    Renommer
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    onClick={() => setMoveTarget(folder)}
                  >
                    Déplacer
                  </button>
                  <ConfirmAction
                    label="Supprimer"
                    title="Supprimer le dossier"
                    message={
                      <>
                        Supprimer <strong>{folder.name}</strong> ? Un dossier non
                        vide est refusé.
                      </>
                    }
                    confirmLabel="Supprimer"
                    danger
                    className="btn btn-ghost btn-small"
                    pending={deleteFolderMutation.isPending}
                    onConfirm={() => deleteFolderMutation.mutate(folder.id)}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="section" aria-labelledby="objects-title">
        <h2 id="objects-title">
          Objets{currentName ? ` — ${currentName}` : " — racine"}
        </h2>
        <div className="search">
          <label className="field">
            <span className="visually-hidden">Rechercher un fichier</span>
            <input
              type="text"
              name="filter"
              placeholder="Rechercher par nom…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </label>
        </div>
        {needle && objectsQuery.hasNextPage ? (
          <p className="muted">Recherche limitée aux objets déjà chargés.</p>
        ) : null}

        {objectsQuery.isError ? (
          <p role="alert" className="alert alert-error">
            Catalogue indisponible. Aucune donnée en cache n'est présentée comme
            actuelle.
          </p>
        ) : objectsQuery.isPending ? (
          <p className="muted">Chargement du catalogue…</p>
        ) : visible.length === 0 ? (
          <p className="empty">
            {needle
              ? "Aucun fichier ne correspond à cette recherche."
              : "Aucun fichier dans ce dossier."}
          </p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Nom</th>
                  <th scope="col">Type</th>
                  <th scope="col">Taille</th>
                  <th scope="col">État</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.id}>
                    <td className="name">{item.display_name}</td>
                    <td className="muted">{item.content_type}</td>
                    <td className="num">
                      {formatBytes(
                        item.status === "pending" && item.expected_size_bytes != null
                          ? item.expected_size_bytes
                          : item.size_bytes,
                      )}
                    </td>
                    <td>{statusChip(item.status)}</td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="btn btn-small"
                        disabled={item.status !== "available"}
                        onClick={() => void handleDownload(item)}
                      >
                        Télécharger
                      </button>
                      <button
                        type="button"
                        className="btn btn-small"
                        onClick={() => setMoveObjectTarget(item)}
                      >
                        Déplacer
                      </button>
                      <ConfirmAction
                        label="Supprimer"
                        title="Supprimer l'objet"
                        message={
                          <>
                            Marquer <strong>{item.display_name}</strong> comme
                            supprimé ? Les octets restent jusqu'à une purge.
                          </>
                        }
                        confirmLabel="Supprimer"
                        danger
                        className="btn btn-small"
                        pending={deleteObjectMutation.isPending}
                        onConfirm={() => deleteObjectMutation.mutate(item.id)}
                      />
                      {canPurge ? (
                        <ConfirmAction
                          label="Purger"
                          title="Purger définitivement"
                          message={
                            <>
                              Supprimer définitivement{" "}
                              <strong>{item.display_name}</strong> et ses octets ?
                              Action irréversible.
                            </>
                          }
                          confirmLabel="Purger"
                          danger
                          className="btn btn-small"
                          pending={purgeMutation.isPending}
                          onConfirm={() => purgeMutation.mutate(item.id)}
                        />
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
        {downloadError ? (
          <p role="alert" className="alert alert-error">
            {downloadError}
          </p>
        ) : null}
        {downloadStatus ? (
          <p role="status" className="alert alert-ok">
            {downloadStatus}
          </p>
        ) : null}
      </section>

      <section className="card" aria-labelledby="upload-title">
        <h2 id="upload-title">Importer{currentName ? ` dans « ${currentName} »` : ""}</h2>
        <p className="muted">
          Intention d'envoi → dépôt direct vers l'URL à courte durée → validation
          avec contrôle d'intégrité (SHA-256 côté serveur).
        </p>
        <form onSubmit={handleUpload} className="form form-inline">
          <label className="field">
            <span>Fichier</span>
            <input
              type="file"
              name="file"
              disabled={transferActive}
              onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
            />
          </label>
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
    </div>
  );
}
