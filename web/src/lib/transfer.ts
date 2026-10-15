/**
 * M03 transfer engine — a single, testable upload state machine.
 *
 * The UI must never show success before the backend confirms it, must not
 * duplicate an upload on an accidental double submit, must distinguish
 * request/upload/validation/availability/failure, and must only retry what the
 * transport says is retryable (bounded exponential backoff with jitter). This
 * module holds that logic with every side effect injected, so it can be tested
 * in isolation (see web/e2e/transfer-engine.spec.ts) and reused by the page.
 *
 * Cancellation is only offered because the backend has an explicit abort
 * endpoint; this module calls it and never pretends to cancel server-side.
 */
import { ApiError, PresignedUploadError } from "./api";
import type { CommitResponse, UploadIntentResponse } from "./api";

export type TransferPhase =
  /** No transfer in flight. */
  | "idle"
  /** Asking the API for a short-lived upload intent. */
  | "requesting-intent"
  /** Bytes are moving directly from the browser to S3. */
  | "uploading"
  /** Backend is verifying size and SHA-256 before availability. */
  | "validating"
  /** Backend confirmed the object is available. */
  | "available"
  | "failed"
  | "cancelled";

export interface TransferState {
  phase: TransferPhase;
  fileName: string;
  sizeBytes: number;
  transferredBytes: number;
  /** 0..1; only meaningful while uploading. */
  progress: number;
  /** Retry count so far (network/URL refresh), for display. */
  attempts: number;
  intentId: string | null;
  error: string | null;
}

export interface TransferResult {
  state: TransferState;
  objectId: string | null;
  checksum?: string;
}

export interface TransferConfig {
  /** Total upload attempts including the first. */
  maxAttempts: number;
  baseDelayMs: number;
  maxDelayMs: number;
  /** How many times an expired presigned URL may be replaced in one transfer. */
  maxIntentRefreshes: number;
}

export const DEFAULT_TRANSFER_CONFIG: TransferConfig = {
  maxAttempts: 3,
  baseDelayMs: 500,
  maxDelayMs: 8000,
  maxIntentRefreshes: 2,
};

export interface TransferDeps {
  requestIntent: (input: {
    fileName: string;
    contentType: string;
    sizeBytes: number;
    folderId: string | null;
    idempotencyKey: string;
  }) => Promise<UploadIntentResponse>;
  upload: (
    url: string,
    file: File,
    opts: {
      headers: Record<string, string>;
      onProgress: (loaded: number, total: number) => void;
      signal?: AbortSignal;
    },
  ) => Promise<void>;
  commit: (id: string) => Promise<CommitResponse>;
  abortIntent: (id: string) => Promise<void>;
  sleep: (ms: number) => Promise<void>;
  random: () => number;
}

export function idleTransfer(file: File | null): TransferState {
  return {
    phase: "idle",
    fileName: file?.name ?? "",
    sizeBytes: file?.size ?? 0,
    transferredBytes: 0,
    progress: 0,
    attempts: 0,
    intentId: null,
    error: null,
  };
}

/**
 * Bounded exponential backoff with *equal jitter*.
 *
 * The exponential ceiling is ``base * 2**attempt`` capped at ``maxDelayMs``;
 * the returned delay is uniformly distributed between half the ceiling and the
 * full ceiling, so many clients cannot retry in lockstep (thundering herd)
 * while the expected wait still grows.
 */
export function backoffDelay(
  attempt: number,
  config: Pick<TransferConfig, "baseDelayMs" | "maxDelayMs">,
  random: () => number = Math.random,
): number {
  const ceiling = Math.min(config.maxDelayMs, config.baseDelayMs * 2 ** Math.max(0, attempt));
  return Math.floor(ceiling / 2 + random() * (ceiling / 2));
}

type Classification = "retryable" | "expired" | "aborted" | "fatal";

function classifyHttp(status: number): Classification {
  if (status === 403) return "expired";
  if (status === 408 || status === 410 || status === 425 || status === 429) return "retryable";
  if (status >= 500) return "retryable";
  return "fatal";
}

export function classifyError(err: unknown): Classification {
  if (err instanceof PresignedUploadError) {
    if (err.kind === "aborted") return "aborted";
    if (err.kind === "expired") return "expired";
    if (err.kind === "network") return "retryable";
    return classifyHttp(err.status);
  }
  if (err instanceof ApiError) {
    return classifyHttp(err.status);
  }
  return "fatal";
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return "Échec du transfert.";
}

function isNearExpiry(intent: UploadIntentResponse, nowMs: number): boolean {
  if (!intent.expires_at) return false;
  // Replace the URL a few seconds early to avoid racing the expiry.
  return nowMs / 1000 >= intent.expires_at - 5;
}

export interface RunTransferOptions {
  folderId: string | null;
  /** Stable per-submission key: reused by automatic retries, new on a new submit. */
  idempotencyKey: string;
  signal?: AbortSignal;
  onUpdate?: (state: TransferState) => void;
  config?: Partial<TransferConfig>;
  now?: () => number;
}

/**
 * Drive one upload to a terminal state.
 *
 * Never resolves ``available`` unless ``commit`` succeeded. A failed transfer
 * leaves no misleading success state: the phase is ``failed`` (or ``cancelled``)
 * and the caller can start a fresh submission with a new idempotency key.
 */
export async function runTransfer(
  file: File,
  deps: TransferDeps,
  options: RunTransferOptions,
): Promise<TransferResult> {
  const config: TransferConfig = { ...DEFAULT_TRANSFER_CONFIG, ...options.config };
  const now = options.now ?? (() => Date.now());
  let state: TransferState = idleTransfer(file);
  const emit = (patch: Partial<TransferState>): void => {
    state = { ...state, ...patch };
    options.onUpdate?.(state);
  };
  const aborted = (): boolean => options.signal?.aborted === true;

  let intent: UploadIntentResponse | null = null;
  let attempts = 0;
  let refreshes = 0;

  const cancel = async (): Promise<TransferResult> => {
    const id = intent?.id ?? null;
    if (id) {
      try {
        await deps.abortIntent(id);
      } catch {
        // Best effort: a storage failure must not break local cancellation.
      }
    }
    emit({ phase: "cancelled", error: null, intentId: id });
    return { state, objectId: id };
  };

  const requestIntent = async (): Promise<UploadIntentResponse | null> => {
    if (intent) return intent;
    try {
      const created = await deps.requestIntent({
        fileName: file.name,
        contentType: file.type || "application/octet-stream",
        sizeBytes: file.size,
        folderId: options.folderId,
        idempotencyKey: options.idempotencyKey,
      });
      intent = created;
      emit({ phase: "uploading", intentId: created.id, error: null });
      return created;
    } catch (err) {
      if (aborted()) return null;
      if (classifyError(err) === "retryable" && attempts < config.maxAttempts - 1) {
        attempts += 1;
        const delay = backoffDelay(attempts - 1, config, deps.random);
        emit({ attempts, error: messageOf(err) });
        await deps.sleep(delay);
        return requestIntent();
      }
      emit({ phase: "failed", error: messageOf(err) });
      return null;
    }
  };

  emit({ phase: "requesting-intent" });

  // Sequential state machine: each iteration is one upload attempt.
  for (;;) {
    if (aborted()) return cancel();

    const current = await requestIntent();
    if (!current) {
      // A cancel that raced the intent request must still end as cancelled;
      // otherwise there is no live intent to reference.
      if (aborted()) return cancel();
      return { state, objectId: null };
    }

    try {
      await deps.upload(current.upload_url, file, {
        headers: current.headers,
        onProgress: (loaded, total) =>
          emit({
            phase: "uploading",
            transferredBytes: loaded,
            progress: total > 0 ? Math.min(1, loaded / total) : 0,
          }),
        signal: options.signal,
      });
      emit({ phase: "validating", progress: 1, transferredBytes: file.size });
      const committed = await deps.commit(current.id);
      emit({ phase: "available", error: null, intentId: current.id });
      return { state, objectId: current.id, checksum: committed.checksum_sha256 };
    } catch (err) {
      if (aborted() || classifyError(err) === "aborted") {
        return cancel();
      }
      const kind = classifyError(err);
      if (kind === "expired") {
        emit({ error: "URL expirée : renouvellement…" });
        intent = null;
        if (refreshes < config.maxIntentRefreshes) {
          refreshes += 1;
          continue;
        }
        emit({ phase: "failed", error: "URL expirée." });
        return { state, objectId: null };
      }
      if (kind === "retryable" && attempts < config.maxAttempts - 1) {
        attempts += 1;
        const delay = backoffDelay(attempts - 1, config, deps.random);
        emit({ attempts, error: messageOf(err) });
        await deps.sleep(delay);
        if (isNearExpiry(current, now())) intent = null;
        continue;
      }
      emit({ phase: "failed", error: messageOf(err) });
      return { state, objectId: current.id };
    }
  }
}

// ---------------------------------------------------------------------------
// Multi-file upload queue (M03 follow-up, issue #63).
//
// A bounded queue of independent single-file transfers. Each file keeps its own
// state, idempotency key and AbortController, so one failure never stops the
// others, a single file can be cancelled, and only the failed files are retried.
// ---------------------------------------------------------------------------

export interface QueueItem {
  id: string;
  fileName: string;
  sizeBytes: number;
  state: TransferState;
}

export interface QueueState {
  items: QueueItem[];
  concurrency: number;
  /** Files currently transferring. */
  active: number;
  /** Files whose backend commit succeeded. */
  done: number;
  failed: number;
  cancelled: number;
  /** True once every file reached a terminal state. */
  finished: boolean;
}

export interface UploadQueue {
  /** Cancel a single file (aborts its transfer and its backend intent). */
  cancelItem(id: string): void;
  cancelAll(): void;
  /** Re-queue the failed and cancelled files, keeping the success ones. */
  retryFailed(): void;
  /** Resolves with the final queue state once every file has settled. */
  done: Promise<QueueState>;
}

export interface QueueOptions {
  folderId: string | null;
  /** How many files transfer at once (default 3). */
  concurrency?: number;
  signal?: AbortSignal;
  onUpdate?: (queue: QueueState) => void;
  config?: Partial<TransferConfig>;
}

export const DEFAULT_QUEUE_CONCURRENCY = 3;

export function emptyQueue(concurrency = DEFAULT_QUEUE_CONCURRENCY): QueueState {
  return {
    items: [],
    concurrency,
    active: 0,
    done: 0,
    failed: 0,
    cancelled: 0,
    finished: false,
  };
}

function queueItemId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `q-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function startUploadQueue(
  files: File[],
  deps: TransferDeps,
  options: QueueOptions,
): UploadQueue {
  const concurrency = Math.max(1, options.concurrency ?? DEFAULT_QUEUE_CONCURRENCY);

  interface Internal {
    id: string;
    file: File;
    state: TransferState;
    controller: AbortController | null;
    settled: boolean;
  }

  const items: Internal[] = files.map((file) => ({
    id: queueItemId(),
    file,
    state: idleTransfer(file),
    controller: null,
    settled: false,
  }));

  let active = 0;
  let finished = false;
  let resolveDone: (state: QueueState) => void = () => undefined;
  const done = new Promise<QueueState>((resolve) => {
    resolveDone = resolve;
  });

  const snapshot = (): QueueState => ({
    items: items.map((item) => ({
      id: item.id,
      fileName: item.file.name,
      sizeBytes: item.file.size,
      state: item.state,
    })),
    concurrency,
    active,
    done: items.filter((item) => item.state.phase === "available").length,
    failed: items.filter((item) => item.state.phase === "failed").length,
    cancelled: items.filter((item) => item.state.phase === "cancelled").length,
    finished: finished || (active === 0 && items.every((item) => item.settled)),
  });

  const emit = () => options.onUpdate?.(snapshot());

  const maybeFinish = () => {
    if (!finished && active === 0 && items.every((item) => item.settled)) {
      finished = true;
      emit();
      resolveDone(snapshot());
    }
  };

  const runItem = (item: Internal) => {
    if (item.settled) return;
    const controller = new AbortController();
    item.controller = controller;
    if (options.signal) {
      if (options.signal.aborted) controller.abort();
      else options.signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
    active += 1;
    item.state = { ...idleTransfer(item.file), phase: "requesting-intent" };
    emit();
    runTransfer(item.file, deps, {
      folderId: options.folderId,
      idempotencyKey: queueItemId(),
      signal: controller.signal,
      config: options.config,
      onUpdate: (state) => {
        item.state = state;
        emit();
      },
    })
      .catch(() => undefined)
      .finally(() => {
        item.controller = null;
        item.settled = true;
        active -= 1;
        emit();
        pump();
        maybeFinish();
      });
  };

  const nextQueued = (): Internal | undefined =>
    items.find(
      (item) => !item.settled && item.controller === null && item.state.phase === "idle",
    );

  const pump = () => {
    let slot = concurrency - active;
    while (slot > 0) {
      const item = nextQueued();
      if (!item) break;
      runItem(item);
      slot -= 1;
    }
    maybeFinish();
  };

  // Start as soon as the queue is created (unless there is nothing to do).
  pump();

  return {
    cancelItem(id: string) {
      const item = items.find((candidate) => candidate.id === id);
      if (!item || item.settled) return;
      if (item.controller) {
        item.controller.abort();
      } else {
        item.state = { ...item.state, phase: "cancelled" };
        item.settled = true;
        emit();
      }
      maybeFinish();
    },
    cancelAll() {
      for (const item of items) {
        if (item.settled) continue;
        if (item.controller) {
          item.controller.abort();
        } else {
          item.state = { ...item.state, phase: "cancelled" };
          item.settled = true;
        }
      }
      emit();
      maybeFinish();
    },
    retryFailed() {
      let requeued = false;
      for (const item of items) {
        if (item.state.phase === "failed" || item.state.phase === "cancelled") {
          item.state = idleTransfer(item.file);
          item.settled = false;
          requeued = true;
        }
      }
      if (!requeued) return;
      finished = false;
      emit();
      pump();
    },
    done,
  };
}
