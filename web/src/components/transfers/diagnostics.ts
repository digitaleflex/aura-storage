import type { QueueItem, QueueState } from "../../lib/transfer";
import {
  countTransfers,
  failureKindLabel,
  fileCategory,
  scopeBytes,
  displayStatus,
  STATUS_LABEL,
} from "./model";

export const DIAGNOSTIC_SCHEMA = "aura.transfer-diagnostic/v1";

export interface DiagnosticEnvironment {
  userAgent: string;
  language: string;
  online: boolean;
  visibility: string | null;
  viewport: { width: number; height: number } | null;
  devicePixelRatio: number | null;
  timezone: string;
}

export interface DiagnosticContext {
  queue: QueueState;
  startedAt: number | null;
  finishedAt: number | null;
  throughput: number;
  addedAt: number | null;
  now?: number;
}

export interface TransferDiagnostic {
  schema: string;
  reportId: string;
  generatedAt: string;
  file: {
    name: string;
    sizeBytes: number;
    category: string;
  };
  transfer: {
    id: string;
    status: string;
    statusLabel: string;
    phase: string;
    transferredBytes: number;
    progress: number;
    attempts: number;
    failureKind: string | null;
    failureLabel: string;
    error: string | null;
    verifyMode: string | null;
    checksum: string | null;
    commitTiming: { head_ms: number; hash_ms: number; total_ms: number } | null;
    phaseLog: Array<{ phase: string; at: string }>;
    addedAt: string | null;
    phaseSince: string | null;
  };
  session: {
    startedAt: string | null;
    finishedAt: string | null;
    throughputBytesPerSecond: number;
    counts: ReturnType<typeof countTransfers>;
    totalBytes: number;
    transferredBytes: number;
  };
  environment: DiagnosticEnvironment;
}

/** Strip URLs, signatures and token-like fields from a server message. */
export function sanitizeDiagnosticText(
  value: string | null | undefined,
): string | null {
  if (value === null || value === undefined || value === "") return null;
  let text = value.replace(/https?:\/\/[^\s"'<>]+/gi, "[url]");
  text = text.replace(/\bs3:\/\/[^\s"'<>]+/gi, "[s3-url]");
  text = text.replace(
    /\b(authorization|token|secret|signature|x-amz-[a-z0-9-]+)\b\s*[:=]\s*[^\r\n,;]+/gi,
    "$1=[redacted]",
  );
  return text.length > 4000 ? `${text.slice(0, 4000)}…` : text;
}

export function detectEnvironment(): DiagnosticEnvironment {
  const nav = typeof navigator === "undefined" ? undefined : navigator;
  const win = typeof window === "undefined" ? undefined : window;
  return {
    userAgent: nav?.userAgent ?? "unknown",
    language: nav?.language ?? "unknown",
    online: nav?.onLine ?? true,
    visibility:
      typeof document === "undefined" ? null : document.visibilityState,
    viewport: win ? { width: win.innerWidth, height: win.innerHeight } : null,
    devicePixelRatio: win?.devicePixelRatio ?? null,
    timezone:
      Intl.DateTimeFormat().resolvedOptions().timeZone || "unknown",
  };
}

function reportId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `diag-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function iso(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : new Date(value).toISOString();
}

/**
 * Build a support-ready snapshot from the data the engine actually exposes.
 * Missing fields stay null: no invented status code, request id or cause.
 */
export function buildTransferDiagnostic(
  item: QueueItem,
  context: DiagnosticContext,
  environment: DiagnosticEnvironment = detectEnvironment(),
): TransferDiagnostic {
  const now = context.now ?? Date.now();
  const status = displayStatus(item);
  const bytes = scopeBytes(context.queue);
  return {
    schema: DIAGNOSTIC_SCHEMA,
    reportId: reportId(),
    generatedAt: new Date(now).toISOString(),
    file: {
      name: item.fileName,
      sizeBytes: item.sizeBytes,
      category: fileCategory(item.fileName),
    },
    transfer: {
      id: item.id,
      status,
      statusLabel: STATUS_LABEL[status],
      phase: item.state.phase,
      transferredBytes: item.state.transferredBytes,
      progress: item.state.progress,
      attempts: item.state.attempts,
      failureKind: item.state.failureKind ?? null,
      failureLabel: failureKindLabel(item),
      error: sanitizeDiagnosticText(item.state.error),
      verifyMode: item.state.verifyMode ?? null,
      checksum: item.state.checksum || null,
      commitTiming: item.state.commitTiming ?? null,
      phaseLog: (item.state.phaseLog ?? []).map((entry) => ({
        phase: entry.phase,
        at: new Date(entry.at).toISOString(),
      })),
      addedAt: iso(context.addedAt),
      phaseSince: iso(item.state.phaseSince),
    },
    session: {
      startedAt: iso(context.startedAt),
      finishedAt: iso(context.finishedAt),
      throughputBytesPerSecond: context.throughput,
      counts: countTransfers(context.queue),
      totalBytes: bytes.totalBytes,
      transferredBytes: bytes.transferredBytes,
    },
    environment,
  };
}

export function downloadTransferDiagnostic(diagnostic: TransferDiagnostic): void {
  const blob = new Blob([JSON.stringify(diagnostic, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `aura-diagnostic-${diagnostic.reportId}.json`;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
