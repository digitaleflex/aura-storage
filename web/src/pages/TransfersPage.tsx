import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { useTransfers } from "../lib/transferContext";
import { makeToast, ToastStack } from "../components/Toasts";
import type { Toast } from "../components/Toasts";
import { TransfersOverview } from "../components/transfers/TransfersOverview";
import { TransfersToolbar } from "../components/transfers/TransfersToolbar";
import { TransfersFilters } from "../components/transfers/TransfersFilters";
import { TransferList } from "../components/transfers/TransferList";
import {
  TransferCancelDialog,
  TransferDetailsDialog,
} from "../components/transfers/TransferDialogs";
import { TransferIcon } from "../components/transfers/TransferIcon";
import { useOnlineStatus } from "../components/transfers/useOnlineStatus";
import {
  canCancelItem,
  canPauseItem,
  canResumeItem,
  countTransfers,
  addedAt,
  displayStatus,
  failureKindLabel,
  failureTitle,
  fileCategory,
  idlePositions,
  matchesStatus,
  sortItems,
  SORT_DEFAULT_DIRECTION,
  STATUS_LABEL,
} from "../components/transfers/model";
import type {
  DisplayStatus,
  SortDirection,
  SortKey,
  StatusFilter,
} from "../components/transfers/model";
import { formatBytes, parseMegabytes } from "../lib/format";
import { downloadCsv, toCsv } from "../lib/csv";
import {
  buildSessionDiagnostic,
  buildTransferDiagnostic,
  downloadSessionDiagnostic,
  downloadTransferDiagnostic,
} from "../components/transfers/diagnostics";
import { useSession } from "../lib/auth";
import { pendingEntries } from "../lib/uploadJournal";
import type { JournalEntry } from "../lib/uploadJournal";
import type { QueueItem } from "../lib/transfer";

const PAGE_SIZE = 50;
const STATUS_FILTERS: StatusFilter[] = [
  "all",
  "active",
  "queued",
  "paused",
  "completed",
  "failed",
  "cancelled",
];
const SORT_KEYS: SortKey[] = ["added", "name", "size", "status"];
const TYPE_FILTERS = ["all", "audio", "video", "image", "pdf", "archive", "other"] as const;
type TypeFilter = (typeof TYPE_FILTERS)[number];

interface UrlFilters {
  status: StatusFilter;
  q: string;
  type: TypeFilter;
  min: string;
  max: string;
  sort: SortKey;
  dir: SortDirection;
}

/** Read filters from the URL, falling back to defaults on unknown values. */
function readUrlFilters(raw: unknown): UrlFilters {
  const record = (raw ?? {}) as Record<string, unknown>;
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  const status = text(record.status) as StatusFilter;
  const sort = SORT_KEYS.includes(text(record.sort) as SortKey)
    ? (text(record.sort) as SortKey)
    : "added";
  const type = text(record.type) as TypeFilter;
  const direction = text(record.dir) as SortDirection;
  return {
    status: STATUS_FILTERS.includes(status) ? status : "all",
    q: text(record.q),
    type: TYPE_FILTERS.includes(type) ? type : "all",
    min: text(record.min),
    max: text(record.max),
    sort,
    dir:
      direction === "asc" || direction === "desc"
        ? direction
        : SORT_DEFAULT_DIRECTION[sort],
  };
}

/**
 * Transfers console.
 *
 * It is a view over the shell-owned upload queue: starting files still happens
 * in the existing importer on the files page, while progress, filtering,
 * pausing, retrying and cancelling all go through the same engine actions.
 * There is no server-side transfer history, so the page never pretends to show
 * one: it states that the session is being followed.
 */
export function TransfersPage() {
  const transfers = useTransfers();
  const { queue } = transfers;
  const navigate = useNavigate();
  const location = useLocation();
  const session = useSession();
  const owner = session.data?.id ?? null;
  const online = useOnlineStatus();

  // Filters live in the URL: shareable, back/forward friendly, no duplicated
  // state. Only the search text is debounced locally for typing comfort.
  const filters = useMemo(
    () => readUrlFilters(location.search),
    [location.search],
  );
  const [searchDraft, setSearchDraft] = useState(filters.q);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [detailId, setDetailId] = useState<string | null>(null);
  const [cancelRequest, setCancelRequest] = useState<"all" | "selection" | null>(
    null,
  );
  const cancelSelectionRef = useRef<string[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counts = useMemo(() => countTransfers(queue), [queue]);
  const [announcement, setAnnouncement] = useState("");

  // Discrete screen-reader announcements: only status transitions, never bytes.
  const countsRef = useRef(counts);
  const wasFinishedRef = useRef(false);
  const lastAnnounceRef = useRef(0);
  const wasOnlineRef = useRef(transfers.isOnline);
  useEffect(() => {
    const previous = countsRef.current;
    const now = Date.now();
    const deltaCompleted = counts.completed - previous.completed;
    const deltaFailed = counts.failed - previous.failed;
    const deltaCancelled = counts.cancelled - previous.cancelled;
    const deltaQueued = counts.queued - previous.queued;
    const previousFailed = previous.failed;

    if (now - lastAnnounceRef.current >= 2000) {
      let message = "";
      if (counts.total > 0 && queue.finished && !wasFinishedRef.current) {
        message =
          counts.failed > 0
            ? "Importation terminée avec des échecs."
            : "Importation terminée.";
      } else if (deltaFailed > 0) {
        message = `${deltaFailed} nouveau${deltaFailed > 1 ? "x" : ""} échec${
          deltaFailed > 1 ? "s" : ""
        }.`;
      } else if (deltaCancelled > 0) {
        message = `${deltaCancelled} fichier${deltaCancelled > 1 ? "s" : ""} annulé${
          deltaCancelled > 1 ? "s" : ""
        }.`;
      } else if (deltaCompleted > 0) {
        message = `${deltaCompleted} fichier${deltaCompleted > 1 ? "s" : ""} terminé${
          deltaCompleted > 1 ? "s" : ""
        }.`;
      } else if (deltaQueued > 0 && previousFailed > counts.failed) {
        message = `${deltaQueued} fichier${deltaQueued > 1 ? "s" : ""} relancé${
          deltaQueued > 1 ? "s" : ""
        } automatiquement.`;
      }
      if (message) {
        setAnnouncement(message);
        lastAnnounceRef.current = now;
      }
    }
    wasFinishedRef.current = queue.finished;
    countsRef.current = counts;
  }, [counts, queue.finished]);

  useEffect(() => {
    if (wasOnlineRef.current && !transfers.isOnline && queue.items.length > 0) {
      setAnnouncement("Connexion perdue, file suspendue.");
      lastAnnounceRef.current = Date.now();
    } else if (
      !wasOnlineRef.current &&
      transfers.isOnline &&
      queue.items.length > 0
    ) {
      setAnnouncement("Connexion rétablie, reprise automatique.");
      lastAnnounceRef.current = Date.now();
    }
    wasOnlineRef.current = transfers.isOnline;
  }, [transfers.isOnline, queue.items.length]);


  const positions = useMemo(() => idlePositions(queue), [queue]);
  const [clock, setClock] = useState(() => Date.now());
  const [resumable, setResumable] = useState<JournalEntry[]>([]);

  // The journal survives a reload; re-read it when the queue settles so a
  // successful import clears the banner on return.
  useEffect(() => {
    if (!owner) {
      setResumable([]);
      return;
    }
    let cancelled = false;
    void pendingEntries(owner)
      .then((entries) => {
        if (!cancelled) setResumable(entries);
      })
      .catch(() => {
        if (!cancelled) setResumable([]);
      });
    return () => {
      cancelled = true;
    };
  }, [owner, queue.done, queue.finished]);

  useEffect(() => {
    setSearchDraft(filters.q);
  }, [filters.q]);

  // A one-shot clock: duration/ETA refresh once a second, not on every tick.
  useEffect(() => {
    if (transfers.startedAt === null || queue.finished || queue.items.length === 0) {
      return;
    }
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [transfers.startedAt, queue.finished, queue.items.length]);

  // The page is the only place that owns the tab title; restore it on leave.
  useEffect(() => {
    const previous = document.title;
    const failed = counts.failed;
    const active = counts.active;
    document.title =
      failed > 0
        ? `(${failed} échec${failed > 1 ? "s" : ""}) Transferts — AURA Vault`
        : active > 0
          ? `(${active}) Transferts — AURA Vault`
          : "Transferts — AURA Vault";
    return () => {
      document.title = previous;
    };
  }, [counts.active, counts.failed]);

  const wasOfflineRef = useRef(false);
  useEffect(() => {
    if (!transfers.isOnline) {
      wasOfflineRef.current = true;
      return;
    }
    if (wasOfflineRef.current) {
      wasOfflineRef.current = false;
      if (queue.items.length > 0) {
        notify("ok", "Connexion rétablie : la file reprend automatiquement.");
      }
    }
  }, [transfers.isOnline, queue.items.length]);

  const filtered = useMemo(() => {
    const needle = searchDraft.trim().toLowerCase();
    const minBytes = parseMegabytes(filters.min);
    const maxBytes = parseMegabytes(filters.max);
    const matching = queue.items.filter((item) => {
      if (!matchesStatus(item, filters.status)) return false;
      if (needle && !item.fileName.toLowerCase().includes(needle)) return false;
      if (filters.type !== "all" && fileCategory(item.fileName) !== filters.type) {
        return false;
      }
      if (minBytes !== null && item.sizeBytes < minBytes) return false;
      if (maxBytes !== null && item.sizeBytes > maxBytes) return false;
      return true;
    });
    return sortItems(
      matching,
      filters.sort,
      transfers.addedAt,
      filters.dir,
    );
  }, [queue.items, filters, searchDraft, transfers.addedAt]);

  // A new filter set starts at the first page again.
  useEffect(() => {
    setVisible(PAGE_SIZE);
  }, [
    filters.status,
    searchDraft,
    filters.type,
    filters.min,
    filters.max,
    filters.sort,
    filters.dir,
  ]);

  // Debounce the text field into the URL (one replace per pause, not per key).
  useEffect(() => {
    if (searchDraft === filters.q) return;
    const timer = window.setTimeout(() => {
      writeFilters({ q: searchDraft }, true);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchDraft, filters.q]);

  // Drop selections whose file left the queue (clear, new import, etc.).
  const itemIds = useMemo(
    () => new Set(queue.items.map((item) => item.id)),
    [queue.items],
  );
  useEffect(() => {
    setSelected((previous) => {
      let changed = false;
      const next = new Set<string>();
      for (const id of previous) {
        if (itemIds.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : previous;
    });
  }, [itemIds]);

  const selectedExisting = useMemo(
    () => [...selected].filter((id) => itemIds.has(id)),
    [selected, itemIds],
  );
  const selectedItems = useMemo(
    () => queue.items.filter((item) => selected.has(item.id)),
    [queue.items, selected],
  );

  const pauseableSelection = selectedItems.filter((item) => canPauseItem(item));
  const resumeableSelection = selectedItems.filter((item) => canResumeItem(item));
  const cancelableSelection = selectedItems.filter((item) => canCancelItem(item));

  const canPause = queue.items.some((item) => canPauseItem(item));
  const canResume =
    queue.schedulerPaused || queue.items.some((item) => canResumeItem(item));
  const canCancel = queue.items.some((item) => canCancelItem(item));
  const canClear = queue.finished && queue.items.length > 0;
  const liveCount = queue.items.filter((item) => canCancelItem(item)).length;

  // Brief row highlight when a file reaches a terminal state.
  const [highlights, setHighlights] = useState<
    Map<string, "success" | "danger">
  >(() => new Map());
  const statusesRef = useRef(new Map<string, DisplayStatus>());
  const highlightTimersRef = useRef(new Map<string, number>());
  useEffect(() => {
    const nextStatuses = new Map<string, DisplayStatus>();
    const updates = new Map<string, "success" | "danger">();
    for (const item of queue.items) {
      const status = displayStatus(item);
      nextStatuses.set(item.id, status);
      const previous = statusesRef.current.get(item.id);
      if (
        previous !== undefined &&
        previous !== status &&
        (status === "completed" || status === "failed")
      ) {
        updates.set(item.id, status === "completed" ? "success" : "danger");
        const existing = highlightTimersRef.current.get(item.id);
        if (existing) window.clearTimeout(existing);
        const timer = window.setTimeout(() => {
          setHighlights((current) => {
            const next = new Map(current);
            next.delete(item.id);
            return next;
          });
          highlightTimersRef.current.delete(item.id);
        }, 900);
        highlightTimersRef.current.set(item.id, timer);
      }
    }
    statusesRef.current = nextStatuses;
    if (updates.size > 0) {
      setHighlights((current) => {
        const next = new Map(current);
        for (const [id, tone] of updates) next.set(id, tone);
        return next;
      });
    }
  }, [queue.items]);
  useEffect(() => {
    const timers = highlightTimersRef.current;
    return () => {
      for (const timer of timers.values()) window.clearTimeout(timer);
    };
  }, []);

  const cancelPreview = useMemo(() => {
    const ids =
      cancelRequest === "selection" ? new Set(cancelSelectionRef.current) : null;
    const scoped = ids
      ? queue.items.filter((item) => ids.has(item.id))
      : queue.items;
    return {
      active: scoped.filter((item) =>
        ["requesting-intent", "uploading", "validating"].includes(item.state.phase),
      ).length,
      queued: scoped.filter((item) => item.state.phase === "idle").length,
      completed: scoped.filter((item) => item.state.phase === "available").length,
    };
  }, [queue.items, cancelRequest]);

  function notify(kind: Toast["kind"], text: string) {
    setToasts((current) => [...current.slice(-3), makeToast(kind, text)]);
  }

  async function copyText(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      notify("ok", `${label} copié.`);
    } catch {
      notify("error", "Copie impossible dans ce navigateur.");
    }
  }

  function handleDownloadDiagnostic(item: QueueItem) {
    const diagnostic = buildTransferDiagnostic(item, {
      queue,
      startedAt: transfers.startedAt,
      finishedAt: transfers.finishedAt,
      throughput: transfers.throughput,
      smoothedThroughput: transfers.smoothedThroughput,
      rateHistory: transfers.rateHistory,
      itemRates: transfers.itemRates,
      addedAtById: transfers.addedAt,
    });
    downloadTransferDiagnostic(diagnostic);
    notify("ok", "Diagnostic téléchargé.");
  }

  function handleDownloadSessionDiagnostic() {
    const diagnostic = buildSessionDiagnostic(queue.items, {
      queue,
      startedAt: transfers.startedAt,
      finishedAt: transfers.finishedAt,
      throughput: transfers.throughput,
      smoothedThroughput: transfers.smoothedThroughput,
      rateHistory: transfers.rateHistory,
      itemRates: transfers.itemRates,
      addedAtById: transfers.addedAt,
    });
    downloadSessionDiagnostic(diagnostic);
    notify("ok", "Diagnostic de session téléchargé.");
  }

  function handleCopyName(item: QueueItem) {
    void copyText(item.fileName, "Nom du fichier");
  }

  function handleCopyError(item: QueueItem) {
    void copyText(
      `${item.fileName} — ${failureTitle(item)} — ${
        item.state.error ?? "aucun message serveur"
      }`,
      "Erreur",
    );
  }

  function selectBy(filter: StatusFilter) {
    const ids = queue.items
      .filter((item) => matchesStatus(item, filter))
      .map((item) => item.id);
    if (ids.length === 0) return;
    setSelected((previous) => new Set([...previous, ...ids]));
    notify(
      "info",
      `${ids.length} transfert${ids.length > 1 ? "s" : ""} ajouté${
        ids.length > 1 ? "s" : ""
      } à la sélection.`,
    );
  }

  function handleResumeImport() {
    void navigate({
      to: "/",
      search: (previous) => ({
        ...(previous as Record<string, unknown>),
        import: "1",
      }),
    });
  }

  function handleRetryConnection() {
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      notify("error", "Toujours hors-ligne : la file reste suspendue.");
      return;
    }
    if (queue.items.length === 0) {
      notify("ok", "Connexion rétablie.");
      return;
    }
    handleResumeAll();
  }

  function handleAddFiles() {
    void navigate({
      to: "/",
      search: (previous) => ({
        ...(previous as Record<string, unknown>),
        import: "1",
      }),
    });
  }

  function writeFilters(patch: Partial<UrlFilters>, replace = false) {
    void navigate({
      to: "/transfers",
      search: (previous) => {
        const current = readUrlFilters(previous);
        const merged = { ...current, ...patch };
        const next = { ...(previous as Record<string, unknown>) };
        next.status = merged.status === "all" ? undefined : merged.status;
        next.q = merged.q.trim() ? merged.q : undefined;
        next.type = merged.type === "all" ? undefined : merged.type;
        next.min = merged.min.trim() ? merged.min : undefined;
        next.max = merged.max.trim() ? merged.max : undefined;
        next.sort = merged.sort === "added" ? undefined : merged.sort;
        next.dir =
          merged.dir === SORT_DEFAULT_DIRECTION[merged.sort]
            ? undefined
            : merged.dir;
        return next;
      },
      replace,
    });
  }

  function handleSort(key: SortKey) {
    if (filters.sort === key) {
      writeFilters({ dir: filters.dir === "asc" ? "desc" : "asc" });
    } else {
      writeFilters({ sort: key, dir: SORT_DEFAULT_DIRECTION[key] });
    }
  }

  function resetFilters() {
    setSearchDraft("");
    void navigate({
      to: "/transfers",
      search: (previous) => {
        const next = { ...(previous as Record<string, unknown>) };
        delete next.status;
        delete next.q;
        delete next.type;
        delete next.min;
        delete next.max;
        delete next.sort;
        delete next.dir;
        return next;
      },
    });
  }

  function handlePauseAll() {
    const count = queue.items.filter((item) => canPauseItem(item)).length;
    transfers.pauseAll();
    notify("info", `${count} transfert${count > 1 ? "s" : ""} en attente suspendu${count > 1 ? "s" : ""}.`);
  }

  function handleResumeAll() {
    const count = queue.items.filter((item) => canResumeItem(item)).length;
    transfers.resumeAll();
    notify("info", `Reprise demandée pour ${count} transfert${count > 1 ? "s" : ""}.`);
  }

  function handleBulkPause() {
    for (const item of pauseableSelection) transfers.pauseItem(item.id);
    notify(
      "info",
      `${pauseableSelection.length} transfert${pauseableSelection.length > 1 ? "s" : ""} suspendu${pauseableSelection.length > 1 ? "s" : ""}.`,
    );
  }

  function handleBulkResume() {
    for (const item of resumeableSelection) transfers.resumeItem(item.id);
    notify(
      "info",
      `${resumeableSelection.length} transfert${resumeableSelection.length > 1 ? "s" : ""} repris.`,
    );
  }

  function requestCancelAll() {
    cancelSelectionRef.current = [];
    setCancelRequest("all");
  }

  function requestCancelSelection() {
    cancelSelectionRef.current = cancelableSelection.map((item) => item.id);
    setCancelRequest("selection");
  }

  function confirmCancel() {
    if (cancelRequest === "all") {
      const count = liveCount;
      transfers.cancelAll();
      notify("info", `Annulation demandée pour ${count} transfert${count > 1 ? "s" : ""}.`);
    } else {
      const ids = cancelSelectionRef.current;
      for (const id of ids) transfers.cancelItem(id);
      notify("info", `Annulation demandée pour ${ids.length} transfert${ids.length > 1 ? "s" : ""}.`);
    }
    cancelSelectionRef.current = [];
    setCancelRequest(null);
  }

  function handleRetry(id: string) {
    transfers.retryItem(id);
    notify("info", "Nouvelle tentative demandée.");
  }

  function handleRetryFailed() {
    // Only actual failures: cancelled rows have their own retry entry and must
    // not be restarted just because the user asked to retry the failures.
    const failed = queue.items.filter((item) => item.state.phase === "failed");
    for (const item of failed) transfers.retryItem(item.id);
    notify(
      "info",
      `Nouvelle tentative demandée pour ${failed.length} transfert${failed.length > 1 ? "s" : ""}.`,
    );
  }

  function handleRowCancel(id: string) {
    transfers.cancelItem(id);
    notify("info", "Annulation demandée pour ce transfert.");
  }

  function handleExport() {
    const rows = filtered.map((item) => {
      const status = displayStatus(item);
      const added = transfers.addedAt.get(item.id) ?? addedAt(item);
      return [
        item.fileName,
        item.sizeBytes,
        item.state.transferredBytes,
        STATUS_LABEL[status],
        item.state.attempts,
        failureKindLabel(item),
        item.state.error ?? "",
        added !== null ? new Date(added).toISOString() : "",
        item.state.phaseSince !== undefined
          ? new Date(item.state.phaseSince).toISOString()
          : "",
      ];
    });
    const csv = toCsv(
      [
        "Nom",
        "Taille (octets)",
        "Transféré (octets)",
        "Statut",
        "Tentatives",
        "Type d'échec",
        "Message d'erreur",
        "Ajouté le",
        "Dernier changement",
      ],
      rows,
    );
    const stamp = new Date()
      .toISOString()
      .slice(0, 16)
      .replace(/[-:T]/g, "");
    downloadCsv(`aura-transferts-${stamp}.csv`, csv);
    notify(
      "ok",
      `${rows.length} ligne${rows.length > 1 ? "s" : ""} exportée${
        rows.length > 1 ? "s" : ""
      }.`,
    );
  }

  function handleClear() {
    transfers.clear();
    setSelected(new Set());
    notify("ok", "File terminée effacée de cette session.");
  }

  function toggleSelected(id: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((previous) => {
      const allSelected =
        filtered.length > 0 && filtered.every((item) => previous.has(item.id));
      if (allSelected) {
        const next = new Set(previous);
        for (const item of filtered) next.delete(item.id);
        return next;
      }
      return new Set([...previous, ...filtered.map((item) => item.id)]);
    });
  }

  const detailItem = detailId
    ? (queue.items.find((item) => item.id === detailId) ?? null)
    : null;

  return (
    <div className="transfers-page" data-testid="transfers-page">
      <header className="transfers-head">
        <div>
          <h1>Transferts</h1>
          <p className="transfers-subtitle">
            Importation de fichiers · Stockage chiffré et sécurisé
          </p>
        </div>
        <span className="transfers-session-chip">
          <TransferIcon name="shield" size={15} />
          Session courante
        </span>
        <Link to="/diagnostic" className="btn btn-small">
          Diagnostic réseau
        </Link>
      </header>

      <TransfersOverview
        queue={queue}
        throughput={transfers.throughput}
        rateHistory={transfers.rateHistory}
        smoothedThroughput={transfers.smoothedThroughput}
        startedAt={transfers.startedAt}
        finishedAt={transfers.finishedAt}
        now={clock}
      />

      {!online ? (
        <div className="transfers-offline" role="status">
          <span className="transfers-offline-icon" aria-hidden="true">
            <TransferIcon name="alert" size={20} />
          </span>
          <div className="transfers-offline-copy">
            <strong>Connexion perdue</strong>
            <p>
              La file est suspendue : la reprise est automatique dès le retour
              du réseau. Les fichiers déjà commencés ne sont pas perdus.
            </p>
          </div>
          <button type="button" className="btn btn-small" onClick={handleRetryConnection}>
            Réessayer
          </button>
        </div>
      ) : null}

      {queue.items.length === 0 && resumable.length > 0 ? (
        <div className="transfers-resume" role="status">
          <span className="transfers-resume-icon" aria-hidden="true">
            <TransferIcon name="upload" size={20} />
          </span>
          <div className="transfers-resume-copy">
            <strong>Import interrompu</strong>
            <p>
              {resumable.length} fichier{resumable.length > 1 ? "s" : ""} (
              {formatBytes(
                resumable.reduce((sum, entry) => sum + entry.size, 0),
              )}
              ) récupérable{resumable.length > 1 ? "s" : ""}. Sélectionnez les
              mêmes fichiers pour reprendre : ceux déjà confirmés ne seront pas
              renvoyés.
            </p>
          </div>
          <button type="button" className="btn btn-primary" onClick={handleResumeImport}>
            Reprendre l'import
          </button>
        </div>
      ) : resumable.length > 0 ? (
        <div className="transfers-resume" role="status">
          <span className="transfers-resume-icon" aria-hidden="true">
            <TransferIcon name="upload" size={20} />
          </span>
          <div className="transfers-resume-copy">
            <strong>Import interrompu</strong>
            <p>
              {resumable.length} fichier{resumable.length > 1 ? "s" : ""} (
              {formatBytes(
                resumable.reduce((sum, entry) => sum + entry.size, 0),
              )}
              ) récupérable{resumable.length > 1 ? "s" : ""}. Sélectionnez les
              mêmes fichiers pour reprendre : ceux déjà confirmés ne seront pas
              renvoyés.
            </p>
          </div>
          <button type="button" className="btn btn-primary" onClick={handleResumeImport}>
            Reprendre l'import
          </button>
        </div>
      ) : null}

      {counts.failed > 0 && (
        <div className="transfers-global-error" role="alert">
          <span className="transfers-global-error-icon" aria-hidden="true">
            <TransferIcon name="alert" size={20} />
          </span>
          <div className="transfers-global-error-copy">
            <strong>
              {counts.failed} transfert{counts.failed > 1 ? "s" : ""} en échec
            </strong>
            <p>
              Cliquez sur un fichier pour voir le détail et réessayer.
            </p>
          </div>
        </div>
      )}

      <TransfersToolbar
        canPause={canPause}
        canResume={canResume}
        canCancel={canCancel}
        canClear={canClear}
        activeCount={counts.active}
        failedCount={counts.failed}
        queuedCount={counts.queued}
        onSelectFailed={() => selectBy("failed")}
        onSelectActive={() => selectBy("active")}
        onSelectQueued={() => selectBy("queued")}
        exportCount={filtered.length}
        onExport={handleExport}
        onDownloadSessionDiagnostic={handleDownloadSessionDiagnostic}
        onPauseAll={handlePauseAll}
        onResumeAll={handleResumeAll}
        onCancelAll={requestCancelAll}
        onAddFiles={handleAddFiles}
        onClear={handleClear}
        onResetFilters={resetFilters}
        onRetryFailed={handleRetryFailed}
      />

      <TransfersFilters
        counts={counts}
        status={filters.status}
        onStatus={(value) => writeFilters({ status: value })}
        search={searchDraft}
        onSearch={setSearchDraft}
        advancedOpen={advancedOpen}
        onToggleAdvanced={() => setAdvancedOpen((open) => !open)}
        typeFilter={filters.type}
        onTypeFilter={(value) => writeFilters({ type: value as TypeFilter })}
        minSize={filters.min}
        onMinSize={(value) => writeFilters({ min: value }, true)}
        maxSize={filters.max}
        onMaxSize={(value) => writeFilters({ max: value }, true)}
        sort={filters.sort}
        onSort={(value) => writeFilters({ sort: value })}
        sortDirection={filters.dir}
        onSortDirection={(value) => writeFilters({ dir: value })}
        onReset={resetFilters}
      />

      {selectedExisting.length > 0 ? (
        <div className="transfers-bulk" role="group" aria-label="Actions sur la sélection">
          <span className="transfers-bulk-count">
            {selectedExisting.length} sélectionné{selectedExisting.length > 1 ? "s" : ""}
          </span>
          <div className="transfers-bulk-actions">
            <button
              type="button"
              className="btn btn-small"
              disabled={pauseableSelection.length === 0}
              title={
                pauseableSelection.length === 0
                  ? "Aucun transfert sélectionné n'est en attente."
                  : undefined
              }
              onClick={handleBulkPause}
            >
              Mettre en pause
            </button>
            <button
              type="button"
              className="btn btn-small"
              disabled={resumeableSelection.length === 0}
              title={
                resumeableSelection.length === 0
                  ? "Aucun transfert sélectionné n'est en pause."
                  : undefined
              }
              onClick={handleBulkResume}
            >
              Reprendre
            </button>
            <button
              type="button"
              className="btn btn-small btn-danger"
              disabled={cancelableSelection.length === 0}
              title={
                cancelableSelection.length === 0
                  ? "Aucun transfert sélectionné n'est encore actif."
                  : undefined
              }
              onClick={requestCancelSelection}
            >
              Annuler
            </button>
            <button
              type="button"
              className="btn btn-small btn-ghost"
              onClick={() => setSelected(new Set())}
            >
              Désélectionner
            </button>
          </div>
        </div>
      ) : null}

      {queue.items.length === 0 ? (
        <section className="transfers-empty" aria-labelledby="transfers-empty-title">
          <span className="transfers-empty-icon" aria-hidden="true">
            <TransferIcon name="upload" size={28} />
          </span>
          <h2 id="transfers-empty-title">Aucun transfert dans cette session</h2>
          <p>
            Les transferts sont suivis pour la session de navigateur en cours :
            un rechargement de page efface la file. Vous pouvez renvoyer les
            fichiers depuis la page Fichiers.
          </p>
          <button type="button" className="btn btn-primary" onClick={handleAddFiles}>
            <TransferIcon name="plus" size={16} />
            Ajouter des fichiers
          </button>
        </section>
      ) : filtered.length === 0 ? (
        <section className="transfers-empty" aria-labelledby="transfers-noresult-title">
          <span className="transfers-empty-icon" aria-hidden="true">
            <TransferIcon name="search" size={26} />
          </span>
          <h2 id="transfers-noresult-title">Aucun fichier ne correspond à ces filtres</h2>
          <p>Élargissez la recherche ou revenez au filtre « Tous ».</p>
          <button type="button" className="btn" onClick={resetFilters}>
            Réinitialiser les filtres
          </button>
        </section>
      ) : (
        <TransferList
          items={filtered}
          visibleCount={visible}
          selected={selected}
          itemRates={transfers.itemRates}
          positions={positions}
          addedAtById={transfers.addedAt}
          highlights={highlights}
          sort={filters.sort}
          sortDirection={filters.dir}
          onSort={handleSort}
          onToggle={toggleSelected}
          onToggleAll={toggleAll}
          onPause={transfers.pauseItem}
          onResume={transfers.resumeItem}
          onCancel={handleRowCancel}
          onRetry={handleRetry}
          onDetails={setDetailId}
          onCopyError={handleCopyError}
          onDownloadDiagnostic={handleDownloadDiagnostic}
          onShowMore={() => setVisible((value) => value + PAGE_SIZE)}
        />
      )}

      <p className="visually-hidden" role="status">
        {queue.done}/{queue.items.length} fichiers transférés
      </p>
      <p className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>

      <TransferDetailsDialog
        item={detailItem}
        onClose={() => setDetailId(null)}
        onRetry={handleRetry}
        onCancel={(id) => {
          transfers.cancelItem(id);
          notify("info", "Annulation demandée pour ce transfert.");
        }}
        onCopyName={handleCopyName}
        onCopyError={handleCopyError}
        onDownloadDiagnostic={handleDownloadDiagnostic}
        addedAtById={transfers.addedAt}
      />

      <TransferCancelDialog
        open={cancelRequest !== null}
        preview={cancelPreview}
        scope={cancelRequest === "selection" ? "selection" : "all"}
        onClose={() => setCancelRequest(null)}
        onConfirm={confirmCancel}
      />

      <ToastStack
        toasts={toasts}
        onDismiss={(id) =>
          setToasts((current) => current.filter((toast) => toast.id !== id))
        }
      />
    </div>
  );
}
