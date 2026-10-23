import type { QueueItem, QueueState, TransferPhase } from "../../lib/transfer";

/** User-facing state of one file, derived from the engine phase + pause flag. */
export type DisplayStatus =
  | "queued"
  | "paused"
  | "initializing"
  | "uploading"
  | "verifying"
  | "completed"
  | "failed"
  | "cancelled";

export type StatusFilter =
  | "all"
  | "active"
  | "queued"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

/** Phases during which bytes or validation are actually moving. */
const ACTIVE_PHASES: TransferPhase[] = ["requesting-intent", "uploading", "validating"];

export function displayStatus(item: QueueItem): DisplayStatus {
  switch (item.state.phase) {
    case "idle":
      return item.paused ? "paused" : "queued";
    case "requesting-intent":
      return "initializing";
    case "uploading":
      return "uploading";
    case "validating":
      return "verifying";
    case "available":
      return "completed";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
  }
}

export const STATUS_LABEL: Record<DisplayStatus, string> = {
  queued: "En attente",
  paused: "En pause",
  initializing: "Initialisation",
  uploading: "En cours",
  verifying: "Vérification",
  completed: "Terminé",
  failed: "Échec",
  cancelled: "Annulé",
};

/** Semantic tone used by badges and progress bars. */
export type StatusTone = "info" | "success" | "warning" | "danger" | "muted";

export const STATUS_TONE: Record<DisplayStatus, StatusTone> = {
  queued: "warning",
  paused: "warning",
  initializing: "info",
  uploading: "info",
  verifying: "info",
  completed: "success",
  failed: "danger",
  cancelled: "muted",
};

export function isActive(item: QueueItem): boolean {
  return ACTIVE_PHASES.includes(item.state.phase);
}

/** A file whose outcome is final for this session (available or aborted). */
export function isSettled(item: QueueItem): boolean {
  return item.state.phase === "available" || item.state.phase === "cancelled";
}

/**
 * Whether the engine can still act on the file. Failed items are terminal for
 * the current run but retryable, so they are not "live".
 */
export function isLive(item: QueueItem): boolean {
  return !isSettled(item) && item.state.phase !== "failed";
}

export function canPauseItem(item: QueueItem): boolean {
  // The engine never aborts an in-flight PUT: pausing only holds files that
  // have not started yet. Offering it while uploading would be a lie.
  return item.state.phase === "idle" && !item.paused;
}

export function canResumeItem(item: QueueItem): boolean {
  return item.state.phase === "idle" && item.paused;
}

export function canCancelItem(item: QueueItem): boolean {
  return isLive(item);
}

export function canRetryItem(item: QueueItem): boolean {
  return item.state.phase === "failed" || item.state.phase === "cancelled";
}

export interface TransferCounts {
  total: number;
  active: number;
  queued: number;
  paused: number;
  completed: number;
  failed: number;
  cancelled: number;
  /** Files that count toward progress: everything but cancellations. */
  denominator: number;
}

export function countTransfers(queue: QueueState): TransferCounts {
  const counts: TransferCounts = {
    total: queue.items.length,
    active: 0,
    queued: 0,
    paused: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
    denominator: 0,
  };
  for (const item of queue.items) {
    switch (displayStatus(item)) {
      case "queued":
        counts.queued += 1;
        break;
      case "paused":
        counts.paused += 1;
        break;
      case "initializing":
      case "uploading":
      case "verifying":
        counts.active += 1;
        break;
      case "completed":
        counts.completed += 1;
        break;
      case "failed":
        counts.failed += 1;
        break;
      case "cancelled":
        counts.cancelled += 1;
        break;
    }
  }
  counts.denominator = counts.total - counts.cancelled;
  return counts;
}

/**
 * Zero-based position of each waiting file in the scheduler order. Paused
 * files hold no slot, so they get no position.
 */
export function idlePositions(queue: QueueState): Map<string, number> {
  const positions = new Map<string, number>();
  let index = 0;
  for (const item of queue.items) {
    if (item.state.phase !== "idle" || item.paused) continue;
    positions.set(item.id, index);
    index += 1;
  }
  return positions;
}

/** "Prochain", "2e dans la file", "12e dans la file". */
export function queuePositionLabel(position: number): string {
  if (position <= 0) return "Prochain dans la file";
  return `${position + 1}e dans la file`;
}

export function matchesStatus(item: QueueItem, filter: StatusFilter): boolean {
  if (filter === "all") return true;
  const status = displayStatus(item);
  if (filter === "active") {
    return status === "initializing" || status === "uploading" || status === "verifying";
  }
  return status === filter;
}

/** Bytes shown in the overview: cancellations no longer belong to the import. */
export function scopeBytes(queue: QueueState): {
  totalBytes: number;
  transferredBytes: number;
} {
  let totalBytes = 0;
  let transferredBytes = 0;
  for (const item of queue.items) {
    if (item.state.phase === "cancelled") continue;
    totalBytes += item.sizeBytes;
    transferredBytes += Math.min(item.state.transferredBytes, item.sizeBytes);
  }
  return { totalBytes, transferredBytes };
}

export function filesPercent(counts: TransferCounts): number {
  if (counts.denominator <= 0) return 0;
  return Math.min(100, Math.round((counts.completed / counts.denominator) * 100));
}

export function bytesPercent(totalBytes: number, transferredBytes: number): number {
  if (totalBytes <= 0) return 0;
  return Math.min(100, Math.round((transferredBytes / totalBytes) * 100));
}

/**
 * Estimated seconds left, or null when no honest estimate exists (no rate, no
 * remaining bytes). A paused or empty queue is not "0 seconds".
 */
export function estimatedRemainingSeconds(
  queue: QueueState,
  throughput: number,
): number | null {
  if (throughput <= 0) return null;
  const { totalBytes, transferredBytes } = scopeBytes(queue);
  const remaining = totalBytes - transferredBytes;
  if (remaining <= 0) return null;
  return remaining / throughput;
}

export type SortKey = "added" | "name" | "size" | "status";
export type SortDirection = "asc" | "desc";

/** Natural direction when a column is first selected. */
export const SORT_DEFAULT_DIRECTION: Record<SortKey, SortDirection> = {
  added: "asc",
  name: "asc",
  size: "desc",
  status: "asc",
};

const STATUS_RANK: Record<DisplayStatus, number> = {
  uploading: 0,
  verifying: 1,
  initializing: 2,
  queued: 3,
  paused: 4,
  failed: 5,
  completed: 6,
  cancelled: 7,
};

export function addedAt(item: QueueItem): number | null {
  return item.state.phaseLog?.[0]?.at ?? item.state.phaseSince ?? null;
}

export function sortItems(
  items: QueueItem[],
  sort: SortKey,
  addedAtById?: ReadonlyMap<string, number>,
  direction: SortDirection = SORT_DEFAULT_DIRECTION[sort],
): QueueItem[] {
  const factor = direction === "asc" ? 1 : -1;
  const copy = [...items];
  switch (sort) {
    case "name":
      copy.sort(
        (a, b) => factor * a.fileName.localeCompare(b.fileName, "fr"),
      );
      break;
    case "size":
      copy.sort((a, b) => factor * (a.sizeBytes - b.sizeBytes));
      break;
    case "status":
      copy.sort(
        (a, b) =>
          factor *
          (STATUS_RANK[displayStatus(a)] - STATUS_RANK[displayStatus(b)] ||
            a.fileName.localeCompare(b.fileName, "fr")),
      );
      break;
    case "added":
    default: {
      const at = (item: QueueItem) =>
        addedAtById?.get(item.id) ?? addedAt(item) ?? 0;
      copy.sort((a, b) => factor * (at(a) - at(b)));
      break;
    }
  }
  return copy;
}

export type FileCategory = "audio" | "video" | "image" | "pdf" | "archive" | "other";

export const CATEGORY_LABEL: Record<FileCategory, string> = {
  audio: "Audio",
  video: "Vidéo",
  image: "Image",
  pdf: "PDF",
  archive: "Archive",
  other: "Autre",
};

const CATEGORY_EXTENSIONS: Record<Exclude<FileCategory, "other" | "pdf">, string[]> = {
  audio: ["mp3", "wav", "flac", "ogg", "m4a", "aac", "opus"],
  video: ["mp4", "mov", "avi", "mkv", "webm", "m4v"],
  image: ["png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "heic", "bmp"],
  archive: ["zip", "rar", "7z", "tar", "gz", "bz2", "xz"],
};

export function fileCategory(fileName: string): FileCategory {
  const ext = fileName.includes(".")
    ? fileName.slice(fileName.lastIndexOf(".") + 1).toLowerCase()
    : "";
  if (ext === "pdf") return "pdf";
  for (const [category, extensions] of Object.entries(CATEGORY_EXTENSIONS)) {
    if (extensions.includes(ext)) return category as FileCategory;
  }
  return "other";
}

/** Human explanation of a failure, derived from the engine's classification. */
export function failureTitle(item: QueueItem): string {
  switch (item.state.failureKind) {
    case "retryable":
      return "Interrompu par un incident réseau ou serveur.";
    case "expired":
      return "L'autorisation d'envoi a expiré.";
    case "fatal":
      return "Le serveur a refusé cette tentative.";
    case "aborted":
      return "Transfert interrompu.";
    default:
      return "Le transfert a échoué.";
  }
}

export function failureKindLabel(item: QueueItem): string {
  switch (item.state.failureKind) {
    case "retryable":
      return "Incident réseau ou serveur (nouvelle tentative possible)";
    case "expired":
      return "Autorisation d'envoi expirée";
    case "fatal":
      return "Refus du serveur (réessayer ne changera pas le résultat sans correction)";
    case "aborted":
      return "Interruption demandée";
    default:
      return "Non classifié";
  }
}

export const SORT_LABEL: Record<SortKey, string> = {
  added: "Ajout (ancien d'abord)",
  name: "Nom",
  size: "Taille (décroissante)",
  status: "Statut",
};
