import type { QueueItem, QueueState } from "../../lib/transfer";
import {
  countTransfers,
  displayStatus,
  failureKindLabel,
  fileCategory,
  scopeBytes,
  STATUS_LABEL,
} from "./model";

export const DIAGNOSTIC_SCHEMA = "aura.transfer-diagnostic/v1";
export const SESSION_DIAGNOSTIC_SCHEMA = "aura.transfer-session-diagnostic/v1";

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
  smoothedThroughput: number;
  rateHistory: readonly number[];
  itemRates: ReadonlyMap<string, number>;
  addedAtById: ReadonlyMap<string, number>;
  now?: number;
}

export interface TransferDiagnostic {
  schema: string;
  reportId: string;
  generatedAt: string;
  file: { name: string; sizeBytes: number; category: string };
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
    intentId: string | null;
    intentReplay: boolean | null;
    multipart: { partCount: number; partSizeBytes: number } | null;
    heldParts: number | null;
    missingParts: number | null;
    resumed: boolean;
    itemRateBytesPerSecond: number;
    phaseLog: Array<{ phase: string; at: string }>;
    addedAt: string | null;
    phaseSince: string | null;
  };
  session: SessionSnapshot;
  environment: DiagnosticEnvironment;
}

export interface SessionSnapshot {
  startedAt: string | null;
  finishedAt: string | null;
  throughputBytesPerSecond: number;
  smoothedThroughputBytesPerSecond: number;
  rateHistoryBytesPerSecond: readonly number[];
  counts: ReturnType<typeof countTransfers>;
  concurrency: number;
  maxConcurrency: number;
  active: number;
  schedulerPaused: boolean;
  totalBytes: number;
  transferredBytes: number;
}

export interface SessionDiagnostic {
  schema: string;
  reportId: string;
  generatedAt: string;
  session: SessionSnapshot;
  environment: DiagnosticEnvironment;
  items: TransferDiagnostic["transfer"][];
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

function newReportId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `diag-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function iso(value: number | null | undefined): string | null {
  return value === null || value === undefined
    ? null
    : new Date(value).toISOString();
}

function sessionSnapshot(context: DiagnosticContext): SessionSnapshot {
  const bytes = scopeBytes(context.queue);
  return {
    startedAt: iso(context.startedAt),
    finishedAt: iso(context.finishedAt),
    throughputBytesPerSecond: context.throughput,
    smoothedThroughputBytesPerSecond: context.smoothedThroughput,
    rateHistoryBytesPerSecond: context.rateHistory,
    counts: countTransfers(context.queue),
    concurrency: context.queue.concurrency,
    maxConcurrency: context.queue.maxConcurrency,
    active: context.queue.active,
    schedulerPaused: context.queue.schedulerPaused,
    totalBytes: bytes.totalBytes,
    transferredBytes: bytes.transferredBytes,
  };
}

function describeTransfer(
  item: QueueItem,
  context: DiagnosticContext,
): TransferDiagnostic["transfer"] {
  const status = displayStatus(item);
  return {
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
    intentId: item.state.intentId ?? null,
    intentReplay: item.state.intentReplay ?? null,
    multipart: item.state.multipart ?? null,
    heldParts: item.state.heldParts ?? null,
    missingParts: item.state.missingParts ?? null,
    resumed: item.state.resumed === true,
    itemRateBytesPerSecond: context.itemRates.get(item.id) ?? 0,
    phaseLog: (item.state.phaseLog ?? []).map((entry) => ({
      phase: entry.phase,
      at: new Date(entry.at).toISOString(),
    })),
    addedAt: iso(context.addedAtById.get(item.id)),
    phaseSince: iso(item.state.phaseSince),
  };
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
  return {
    schema: DIAGNOSTIC_SCHEMA,
    reportId: newReportId(),
    generatedAt: new Date(now).toISOString(),
    file: {
      name: item.fileName,
      sizeBytes: item.sizeBytes,
      category: fileCategory(item.fileName),
    },
    transfer: describeTransfer(item, context),
    session: sessionSnapshot(context),
    environment,
  };
}

/** Same telemetry for every file, used to diagnose a slow or resumed session. */
export function buildSessionDiagnostic(
  items: readonly QueueItem[],
  context: DiagnosticContext,
  environment: DiagnosticEnvironment = detectEnvironment(),
): SessionDiagnostic {
  const now = context.now ?? Date.now();
  return {
    schema: SESSION_DIAGNOSTIC_SCHEMA,
    reportId: newReportId(),
    generatedAt: new Date(now).toISOString(),
    session: sessionSnapshot(context),
    environment,
    items: items.map((item) => describeTransfer(item, context)),
  };
}

function downloadJson(filename: string, payload: unknown): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function downloadTransferDiagnostic(diagnostic: TransferDiagnostic): void {
  downloadJson(`aura-diagnostic-${diagnostic.reportId}.json`, diagnostic);
}

export function downloadSessionDiagnostic(diagnostic: SessionDiagnostic): void {
  downloadJson(`aura-session-diagnostic-${diagnostic.reportId}.json`, diagnostic);
}
