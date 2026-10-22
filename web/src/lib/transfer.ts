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
import { describeError } from "./errors";
import type {
  CommitResponse,
  CommitTiming,
  MultipartPartUrls,
  MultipartStatus,
  UploadIntentResponse,
} from "./api";

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
  /**
   * Why a failed transfer stopped. Only `retryable` is worth an automatic
   * retry once the link comes back: `fatal` (rejected bytes, storage full),
   * `expired` (URL renewed too many times) and `aborted` need a decision or
   * a fresh submission, not a silent replay.
   */
  failureKind?: "retryable" | "expired" | "fatal" | "aborted";
  /**
   * Durées du commit serveur, transportées telles quelles depuis la réponse de
   * commit pour que l'affichage puisse les lire sur l'état de l'upload.
   * `null` (ou absent) signifie « pas mesuré pour cette requête » : objet déjà
   * publié, commit gagné par une requête concurrente, ou vérification
   * différée. Ce module ne les interprète jamais.
   */
  commitTiming?: CommitTiming | null;
  /** When (ms since epoch) the current phase began; drives "since 0:42" labels. */
  phaseSince?: number;
  /**
   * What the server is doing while the phase is "validating": `inline` = the
   * commit request is re-reading and hashing the object; `background` = the
   * bytes are stored and the integrity check waits in the server's queue (202).
   */
  verifyMode?: "inline" | "background";
  /** Every phase this file went through, with the time (ms epoch) it began. */
  phaseLog?: Array<{ phase: TransferPhase; at: number }>;
  /** SHA-256 the server recorded once the file is available. */
  checksum?: string;
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
  /** Parts sent at once for one multipart file (#72). */
  partConcurrency: number;
  /** Attempts per part, including the first; a failed part only resends itself. */
  partMaxAttempts: number;
}

export const DEFAULT_TRANSFER_CONFIG: TransferConfig = {
  maxAttempts: 3,
  baseDelayMs: 500,
  maxDelayMs: 8000,
  maxIntentRefreshes: 2,
  partConcurrency: 4,
  partMaxAttempts: 6,
};

/** Part URLs requested per call (the API accepts up to 100). */
const PART_URL_BATCH = 20;

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
    file: Blob,
    opts: {
      headers: Record<string, string>;
      onProgress: (loaded: number, total: number) => void;
      signal?: AbortSignal;
    },
  ) => Promise<void>;
  commit: (id: string) => Promise<CommitResponse>;
  abortIntent: (id: string) => Promise<void>;
  /** Multipart (#72): parts already held, for a resumed upload. */
  multipartStatus?: (id: string) => Promise<MultipartStatus>;
  /** Multipart (#72): presigned PUTs for the given part numbers. */
  partUrls?: (id: string, partNumbers: number[]) => Promise<MultipartPartUrls>;
  /** Current object state, to follow an integrity check that runs after commit (N5). */
  objectStatus?: (id: string) => Promise<{ status: string; checksum_sha256?: string }>;
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
  // 507: the server refused the upload because the storage is full. Retrying
  // cannot help until space is freed.
  if (status === 507) return "fatal";
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
  const fallback =
    err instanceof ApiError
      ? err.detail
      : err instanceof Error
        ? err.message
        : "Échec du transfert.";
  return describeError(err, fallback);
}

function isNearExpiry(intent: UploadIntentResponse, nowMs: number): boolean {
  if (!intent.expires_at) return false;
  // Replace the URL a few seconds early to avoid racing the expiry.
  return nowMs / 1000 >= intent.expires_at - 5;
}

export interface RunTransferOptions {
  /**
   * Called once when the bytes are stored and the server answers "verifying"
   * (N5): the file no longer uses the uplink, so the queue may free its slot.
   */
  onVerifying?: () => void;
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
    // Stamp every phase change so the UI can say how long a step has lasted.
    const changed = patch.phase !== undefined && patch.phase !== state.phase;
    const at = now();
    state = {
      ...state,
      ...patch,
      ...(changed
        ? { phaseSince: at, phaseLog: [...(state.phaseLog ?? []), { phase: patch.phase!, at }] }
        : {}),
    };
    // Leaving the validating phase clears what the server was doing.
    if (changed && patch.phase !== "validating") state = { ...state, verifyMode: undefined };
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
      emit({ phase: "failed", error: messageOf(err), failureKind: classifyError(err) });
      return null;
    }
  };

  /**
   * Multipart upload (#72): ask which parts the storage already holds, send
   * only the others with bounded parallelism, then commit. A failed part is
   * retried alone (backoff + jitter); an expired part URL is re-requested. The
   * server checks the part list itself at commit, and answers 409 if a part is
   * still missing, which starts another round.
   */
  const runMultipart = async (current: UploadIntentResponse): Promise<TransferResult> => {
    const plan = current.multipart;
    if (!plan || !deps.multipartStatus || !deps.partUrls) {
      emit({
        phase: "failed",
        error: "Envoi en plusieurs parties non pris en charge.",
        failureKind: "fatal",
      });
      return { state, objectId: current.id };
    }
    const statusOf = deps.multipartStatus;
    const urlsFor = deps.partUrls;
    const partBytes = plan.part_size_bytes;
    const lengthOf = (n: number) =>
      Math.max(0, Math.min(partBytes, file.size - (n - 1) * partBytes));

    // Control-plane calls (status, part URLs, commit) get the same bounded
    // retry as the single-PUT intent request.
    const withRetry = async <T>(call: () => Promise<T>): Promise<T> => {
      for (let tries = 0; ; tries += 1) {
        try {
          return await call();
        } catch (err) {
          if (aborted() || classifyError(err) !== "retryable" || tries >= config.partMaxAttempts - 1) {
            throw err;
          }
          attempts += 1;
          emit({ attempts, error: messageOf(err) });
          await deps.sleep(backoffDelay(tries, config, deps.random));
        }
      }
    };

    for (let round = 0; ; round += 1) {
      if (aborted()) return cancel();
      let held: number[];
      try {
        held = (await withRetry(() => statusOf(current.id))).uploaded_parts;
      } catch (err) {
        if (aborted()) return cancel();
        emit({ phase: "failed", error: messageOf(err), failureKind: classifyError(err) });
        return { state, objectId: current.id };
      }
      const heldSet = new Set(held);
      const queue: number[] = [];
      for (let n = 1; n <= plan.part_count; n += 1) if (!heldSet.has(n)) queue.push(n);

      let doneBytes = held.reduce((sum, n) => sum + lengthOf(n), 0);
      const inflight = new Map<number, number>();
      const report = () => {
        let moving = doneBytes;
        for (const loaded of inflight.values()) moving += loaded;
        emit({
          phase: "uploading",
          transferredBytes: moving,
          progress: file.size > 0 ? Math.min(1, moving / file.size) : 1,
        });
      };
      report();

      const urls = new Map<number, string>();
      let failure: unknown = null;
      const worker = async (): Promise<void> => {
        for (;;) {
          if (failure !== null || aborted()) return;
          const n = queue.shift();
          if (n === undefined) return;
          let tries = 0;
          let refreshes = 0;
          for (;;) {
            if (aborted()) return;
            try {
              let url = urls.get(n);
              if (!url) {
                const batch = [n, ...queue.filter((m) => !urls.has(m)).slice(0, PART_URL_BATCH - 1)];
                const got = await withRetry(() => urlsFor(current.id, batch));
                for (const part of got.parts) urls.set(part.part_number, part.url);
                url = urls.get(n);
                if (!url) throw new Error("URL de partie manquante.");
              }
              const start = (n - 1) * partBytes;
              await deps.upload(url, file.slice(start, start + lengthOf(n)), {
                headers: {},
                onProgress: (loaded) => {
                  inflight.set(n, loaded);
                  report();
                },
                signal: options.signal,
              });
              inflight.delete(n);
              urls.delete(n);
              doneBytes += lengthOf(n);
              report();
              break;
            } catch (err) {
              inflight.delete(n);
              if (aborted() || classifyError(err) === "aborted") return;
              const kind = classifyError(err);
              if (kind === "expired" && refreshes < config.maxIntentRefreshes + 1) {
                refreshes += 1;
                urls.delete(n);
                continue;
              }
              if (kind === "retryable" && tries < config.partMaxAttempts - 1) {
                tries += 1;
                attempts += 1;
                emit({ attempts, error: messageOf(err) });
                await deps.sleep(backoffDelay(tries - 1, config, deps.random));
                continue;
              }
              failure = err;
              return;
            }
          }
        }
      };
      const workers = Math.max(1, Math.min(config.partConcurrency, queue.length));
      await Promise.all(Array.from({ length: workers }, () => worker()));
      if (aborted()) return cancel();
      if (failure !== null) {
        emit({ phase: "failed", error: messageOf(failure), failureKind: classifyError(failure) });
        return { state, objectId: current.id };
      }

      emit({ phase: "validating", progress: 1, transferredBytes: file.size, error: null, verifyMode: "inline" });
      try {
        const committed = await withRetry(() => deps.commit(current.id));
        return settle(current.id, committed);
      } catch (err) {
        if (aborted()) return cancel();
        // 409: a part is still missing at the storage (lost, or a size
        // mismatch). Ask again and send what is missing, a bounded number of times.
        if (err instanceof ApiError && err.status === 409 && round < 2) continue;
        emit({ phase: "failed", error: messageOf(err), failureKind: classifyError(err) });
        return { state, objectId: current.id };
      }
    }
  };

  /**
   * A large object is checked after commit (202 "verifying", N5): follow its
   * state until the server marks it available or failed. Never reports success
   * before the server does.
   */
  const settle = async (
    id: string,
    committed: {
      status: string;
      checksum_sha256?: string;
      commit_timing?: CommitTiming | null;
    },
  ): Promise<TransferResult> => {
    // Figé avant le suivi : les réponses de `objectStatus` décrivent l'objet et
    // ne portent pas les timings du commit, qui ne valent que pour cette requête.
    const commitTiming = committed.commit_timing ?? null;
    let current = committed;
    if (current.status === "verifying") options.onVerifying?.();
    for (let polls = 0; current.status === "verifying"; polls += 1) {
      if (aborted()) return cancel();
      if (!deps.objectStatus) break;
      emit({ phase: "validating", error: null, verifyMode: "background" });
      await deps.sleep(Math.min(5_000, 1_000 * 2 ** Math.min(polls, 3)));
      try {
        current = await deps.objectStatus(id);
      } catch (err) {
        if (classifyError(err) !== "retryable") {
          emit({ phase: "failed", error: messageOf(err), failureKind: classifyError(err) });
          return { state, objectId: id };
        }
      }
    }
    if (current.status !== "available") {
      emit({
        phase: "failed",
        error:
          current.status === "verifying"
            ? "Vérification d'intégrité en cours côté serveur."
            : "La vérification d'intégrité a échoué.",
        // A server-side verdict does not change by retrying the same bytes.
        failureKind: "fatal",
      });
      return { state, objectId: id };
    }
    emit({
      phase: "available",
      error: null,
      intentId: id,
      progress: 1,
      transferredBytes: file.size,
      // Porté par l'état de la file : l'UI le lit sur l'élément correspondant,
      // aucun affichage n'est décidé ici.
      commitTiming,
      checksum: current.checksum_sha256,
    });
    return { state, objectId: id, checksum: current.checksum_sha256 };
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
    // Already sent (a reload while the server was checking it): no new bytes.
    if (current.status === "available" || current.status === "verifying") {
      emit({ phase: "validating", progress: 1, transferredBytes: file.size });
      return settle(current.id, { status: current.status });
    }
    if (current.upload_mode === "multipart") return runMultipart(current);
    if (!current.upload_url) {
      emit({
        phase: "failed",
        error: "Réponse d'envoi incomplète.",
        failureKind: "retryable",
      });
      return { state, objectId: current.id };
    }

    try {
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
      } catch (err) {
        // 412: the PUT is conditional (If-None-Match: *), so the object already
        // exists on this key, left by an earlier attempt whose commit failed.
        // The bytes are there: go straight to the commit instead of failing.
        if (!(err instanceof PresignedUploadError && err.status === 412)) throw err;
      }
      emit({ phase: "validating", progress: 1, transferredBytes: file.size, verifyMode: "inline" });
      // The bytes are stored: a failing commit retries the commit only, never
      // the whole upload (which would resend everything, then hit 412/409).
      let committed: { status: string; checksum_sha256?: string };
      for (let tries = 0; ; tries += 1) {
        try {
          committed = await deps.commit(current.id);
          break;
        } catch (err) {
          if (aborted() || classifyError(err) === "aborted") return cancel();
          // 504: the server gave up and discarded the bytes; only a re-upload helps.
          const retryable =
            classifyError(err) === "retryable" && !(err instanceof ApiError && err.status === 504);
          if (!retryable) throw err;
          if (tries >= config.maxAttempts - 1) {
            emit({ phase: "failed", error: messageOf(err), failureKind: "retryable" });
            return { state, objectId: current.id };
          }
          attempts += 1;
          emit({ attempts, error: messageOf(err) });
          await deps.sleep(backoffDelay(tries, config, deps.random));
        }
      }
      return settle(current.id, committed);
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
        emit({ phase: "failed", error: "URL expirée.", failureKind: "expired" });
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
      emit({ phase: "failed", error: messageOf(err), failureKind: kind });
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
//
// The queue also owns the browser-lifecycle concerns so a tab switch or an SPA
// navigation cannot silently strand a transfer: progress is driven by XHR
// progress events (never a polling interval), a `beforeunload` guard warns while
// files are in flight, and losing connectivity suspends scheduling (paused)
// instead of failing the remaining files (offline). Pausing never aborts an
// in-flight PUT: the current connection finishes and only new starts are held.
// ---------------------------------------------------------------------------

export interface QueueItem {
  id: string;
  /** Caller-supplied identity (e.g. the upload journal fingerprint). */
  key?: string;
  fileName: string;
  sizeBytes: number;
  state: TransferState;
  /**
   * Suspended by the queue (explicit pause or a connectivity loss). Distinct
   * from a failed item: it is not terminal, carries no error, and keeps its
   * bytes untouched. `state.phase` stays `idle` while it waits, so a paused
   * file reads as "en attente", never as "échec".
   */
  paused: boolean;
}

export interface QueueState {
  items: QueueItem[];
  /** Effective parallelism right now (shrinks while the link is degraded). */
  concurrency: number;
  /** Configured ceiling; concurrency never exceeds it. */
  maxConcurrency: number;
  /** Files currently transferring. */
  active: number;
  /** Files whose backend commit succeeded. */
  done: number;
  failed: number;
  cancelled: number;
  /** Files suspended by an explicit pause or a connectivity loss. */
  paused: number;
  /** True while the scheduler is held (queue-wide pause or offline). */
  schedulerPaused: boolean;
  /** True once every file reached a terminal state. */
  finished: boolean;
}

export interface UploadQueue {
  /** Cancel a single file (aborts its transfer and its backend intent). */
  cancelItem(id: string): void;
  cancelAll(): void;
  /**
   * Suspend one file that has not started yet. An in-flight PUT is never
   * aborted (no resumable multipart yet), so pausing only holds scheduling.
   */
  pauseItem(id: string): void;
  /** Un-suspend one paused file and let the scheduler pick it up again. */
  resumeItem(id: string): void;
  /** Suspend the scheduler and every file that has not started (no abort). */
  pauseAll(): void;
  /** Resume the scheduler and every suspended file. */
  resumeAll(): void;
  /** Re-queue the failed and cancelled files, keeping the success ones. */
  retryFailed(): void;
  /**
   * Re-queue only the files that failed for a transient (network/5xx) reason,
   * e.g. because the link dropped mid-upload. Fatal rejections and user
   * cancellations are left alone. Called automatically on `online`.
   */
  retryTransient(): void;
  /** Re-queue one failed or cancelled file as a fresh submission. */
  retryItem(id: string): void;
  /** Detach the window listeners; safe to call on unmount (idempotent). */
  dispose(): void;
  /** Resolves with the final queue state once every file has settled. */
  done: Promise<QueueState>;
}

export interface QueueOptions {
  /** Minimum gap between progress-only snapshots (default 250 ms; 0 = every event). */
  progressIntervalMs?: number;
  folderId: string | null;
  /** How many files transfer at once (default 10). */
  concurrency?: number;
  /** Alias of `concurrency`; wins when both are provided. Default 10. */
  maxConcurrency?: number;
  /**
   * Delay between the start of two parallel files, in milliseconds.
   * Paces connection bursts against the storage gateway instead of firing
   * every PUT at once (JDownLoader's per-host pacing idea, adapted to our
   * presigned PUTs). 0 disables. Default 250.
   */
  startStaggerMs?: number;
  /**
   * Shrink the effective parallelism after repeated congestion failures and
   * restore it after sustained success (JDownLoader's MaxJumpStrategy idea,
   * adapted from chunks to whole files). Fatal errors and cancellations carry
   * no congestion signal. Default true.
   */
  adaptiveConcurrency?: boolean;
  /** Consecutive congestion failures that cost one parallel slot (scaled by ceiling). */
  congestionThreshold?: number;
  /** Consecutive successes that restore one parallel slot (scaled by ceiling). */
  recoveryThreshold?: number;
  /**
   * When true (default) the queue suspends itself while the browser reports
   * offline and resumes on the `online` event. In-flight PUTs are never
   * aborted; only new scheduling is held. Set false to manage it manually.
   */
  autoPauseOnOffline?: boolean;
  /**
   * When true (default) every file that stopped on a transient error -- a
   * network drop, a 5xx, an expired upload URL -- is put back in the queue
   * automatically when the browser reports it is online again, instead of
   * waiting for the user to click "Réessayer". Fatal failures (bytes
   * rejected, storage full, integrity failure) and cancellations are never
   * replayed. A per-file cap (`maxReconnectRetries`) stops a file that keeps
   * breaking the link from looping forever.
   */
  autoRetryOnReconnect?: boolean;
  /**
   * How many times one file may be re-queued by a reconnect, in total.
   * Default 3. The counter is reset by a manual retry.
   */
  maxReconnectRetries?: number;
  /** Called after a reconnect re-queued files, with how many (for the UI). */
  onAutoRetry?: (count: number) => void;
  signal?: AbortSignal;
  onUpdate?: (queue: QueueState) => void;
  config?: Partial<TransferConfig>;
}

/**
 * Default parallelism. A wide window (10) shares one uplink between ten PUTs, so
 * each file takes ~10/3 longer, trips Traefik's 1200 s readTimeout earlier and
 * makes the server re-read ten objects at once on the same disk (commit rehash
 * is 5.8-7.1x slower under 4 concurrent writes, see
 * docs/engineering/commit-latency-bench.md). Four keeps the link busy without
 * those costs; adaptive concurrency still backs off to 1 on congestion.
 */
export const DEFAULT_QUEUE_CONCURRENCY = 4;
export const DEFAULT_START_STAGGER_MS = 250;
/** Base congestion tolerance, tuned for the historical cap of 3 concurrent files. */
export const DEFAULT_CONGESTION_THRESHOLD = 2;
/** Base recovery target, tuned for the historical cap of 3 concurrent files. */
export const DEFAULT_RECOVERY_THRESHOLD = 3;

/**
 * Scale the adaptive thresholds with the configured ceiling.
 *
 * Narrow queues keep the historical, already-tuned values. A wide queue (10)
 * must not lose a slot after every couple of transient blips, so the shrink
 * tolerance grows (less aggressive reduction) while the restore target shrinks
 * (faster recovery). Both trends are monotonic in the ceiling.
 */
export function adaptiveThresholds(maxConcurrency: number): {
  congestionThreshold: number;
  recoveryThreshold: number;
} {
  if (maxConcurrency <= 3) {
    return {
      congestionThreshold: DEFAULT_CONGESTION_THRESHOLD,
      recoveryThreshold: DEFAULT_RECOVERY_THRESHOLD,
    };
  }
  return {
    // 10 -> 4 consecutive losses per slot lost (instead of 2).
    congestionThreshold: Math.max(
      DEFAULT_CONGESTION_THRESHOLD,
      Math.ceil(maxConcurrency / 3),
    ),
    // 10 -> 2 consecutive wins per slot regained (instead of 3).
    recoveryThreshold: Math.max(2, Math.ceil(6 / maxConcurrency)),
  };
}

export function emptyQueue(concurrency = DEFAULT_QUEUE_CONCURRENCY): QueueState {
  return {
    items: [],
    concurrency,
    maxConcurrency: concurrency,
    active: 0,
    done: 0,
    failed: 0,
    cancelled: 0,
    paused: 0,
    schedulerPaused: false,
    finished: false,
  };
}

function queueItemId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `q-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export interface QueueInput {
  file: File;
  /** Target catalogue folder for this file (defaults to `options.folderId`). */
  folderId?: string | null;
  /** Caller-supplied identity, echoed on the queue item. */
  key?: string;
  /**
   * Stable idempotency key: the same multipart session is resumed (parts kept)
   * across retries and page reloads. Omitted: a fresh key per run.
   */
  idempotencyKey?: string;
}

export function startUploadQueue(
  entries: Array<File | QueueInput>,
  deps: TransferDeps,
  options: QueueOptions,
): UploadQueue {
  const maxConcurrency = Math.max(
    1,
    options.maxConcurrency ?? options.concurrency ?? DEFAULT_QUEUE_CONCURRENCY,
  );
  const startStaggerMs = Math.max(0, options.startStaggerMs ?? DEFAULT_START_STAGGER_MS);
  const adaptive = options.adaptiveConcurrency ?? true;
  const scaled = adaptiveThresholds(maxConcurrency);
  const congestionThreshold = Math.max(
    1,
    options.congestionThreshold ?? scaled.congestionThreshold,
  );
  const recoveryThreshold = Math.max(
    1,
    options.recoveryThreshold ?? scaled.recoveryThreshold,
  );
  const autoPauseOnOffline = options.autoPauseOnOffline ?? true;
  const autoRetryOnReconnect = options.autoRetryOnReconnect ?? true;
  const maxReconnectRetries = Math.max(0, options.maxReconnectRetries ?? 3);
  const defaultFolder = options.folderId ?? null;

  // Effective parallelism, adapted at runtime (see adaptToOutcome). It never
  // exceeds the configured maximum, so the queue can only get gentler.
  let effectiveConcurrency = maxConcurrency;
  let congestedStreak = 0;
  let healthyStreak = 0;
  // Scheduled (staggered) starts not running yet: they hold a slot like actives.
  let pendingStarts = 0;

  interface Internal {
    id: string;
    key: string | undefined;
    idempotencyKey: string | undefined;
    file: File;
    folderId: string | null;
    state: TransferState;
    controller: AbortController | null;
    settled: boolean;
    /** A staggered start is scheduled but not running yet. */
    reserved: boolean;
    /** Suspended: the scheduler must not start (nor restart) this file. */
    paused: boolean;
    /** Automatic re-queues already granted by a reconnect. */
    reconnectRetries: number;
  }

  const items: Internal[] = entries.map((entry) => {
    const input: QueueInput = "file" in entry ? entry : { file: entry };
    return {
      id: queueItemId(),
      key: input.key,
      idempotencyKey: input.idempotencyKey,
      file: input.file,
      folderId: input.folderId !== undefined ? input.folderId : defaultFolder,
      state: idleTransfer(input.file),
      controller: null,
      settled: false,
      reserved: false,
      paused: false,
      reconnectRetries: 0,
    };
  });

  let active = 0;
  // Files whose bytes are stored and only await the server's integrity check:
  // still in flight (finish detection) but no longer holding an upload slot.
  let verifyingSlots = 0;
  let finished = false;
  // Held while the scheduler must not start new files (explicit pause/offline).
  let schedulerPaused = false;
  let resolveDone: (state: QueueState) => void = () => undefined;
  const done = new Promise<QueueState>((resolve) => {
    resolveDone = resolve;
  });

  const snapshot = (): QueueState => ({
    items: items.map((item) => ({
      id: item.id,
      key: item.key,
      fileName: item.file.name,
      sizeBytes: item.file.size,
      state: item.state,
      paused: item.paused,
    })),
    concurrency: effectiveConcurrency,
    maxConcurrency,
    active,
    done: items.filter((item) => item.state.phase === "available").length,
    failed: items.filter((item) => item.state.phase === "failed").length,
    cancelled: items.filter((item) => item.state.phase === "cancelled").length,
    paused: items.filter((item) => !item.settled && item.paused).length,
    schedulerPaused,
    finished: finished || (active === 0 && items.every((item) => item.settled)),
  });

  // Byte-progress events arrive ~20/s per XHR (200/s at ten files). Each emit
  // copies the whole queue and re-renders the page, so progress-only updates
  // are coalesced to one per `progressIntervalMs`; every phase change, and the
  // final state, is emitted at once.
  const progressIntervalMs = Math.max(0, options.progressIntervalMs ?? 250);
  let progressTimer: ReturnType<typeof setTimeout> | null = null;
  let lastEmitAt = 0;
  const emit = () => {
    if (progressTimer !== null) {
      clearTimeout(progressTimer);
      progressTimer = null;
    }
    lastEmitAt = Date.now();
    options.onUpdate?.(snapshot());
  };
  const emitProgress = () => {
    const wait = progressIntervalMs - (Date.now() - lastEmitAt);
    if (wait <= 0) {
      emit();
    } else if (progressTimer === null) {
      progressTimer = setTimeout(emit, wait);
    }
  };

  /**
   * A file that stopped on a transient error is not really finished: the next
   * `online` may restart it, so its listeners must stay attached. Without this
   * the queue detaches them as soon as the last file settles and a network
   * drop would leave the whole import failed until a manual retry.
   */
  const awaitingReconnect = (): boolean =>
    autoRetryOnReconnect &&
    maxReconnectRetries > 0 &&
    items.some(
      (item) =>
        item.state.phase === "failed" &&
        item.state.failureKind === "retryable" &&
        item.reconnectRetries < maxReconnectRetries,
    );

  const maybeFinish = () => {
    if (!finished && active === 0 && items.every((item) => item.settled)) {
      finished = true;
      if (!awaitingReconnect()) detachListeners();
      emit();
      resolveDone(snapshot());
    }
  };

  /**
   * JDownLoader-style adaptation (cf. MaxJumpStrategy.processFinishedChunks):
   * repeated congestion (network errors, 5xx, expired URLs) shrinks the
   * effective parallelism one slot at a time, down to a single file;
   * sustained success restores it one slot at a time. Fatal errors and
   * cancellations carry no congestion signal, so a rejected file or a user
   * cancel never throttles the queue.
   */
  const adaptToOutcome = (item: Internal, lastError: unknown): void => {
    if (!adaptive) return;
    if (item.state.phase === "available") {
      congestedStreak = 0;
      healthyStreak += 1;
      if (healthyStreak >= recoveryThreshold && effectiveConcurrency < maxConcurrency) {
        effectiveConcurrency += 1;
        healthyStreak = 0;
      }
      return;
    }
    if (item.state.phase !== "failed") return; // cancelled: no signal
    healthyStreak = 0;
    const kind = classifyError(lastError);
    if (kind !== "retryable" && kind !== "expired") return;
    congestedStreak += 1;
    if (congestedStreak >= congestionThreshold && effectiveConcurrency > 1) {
      effectiveConcurrency -= 1;
      congestedStreak = 0;
    }
  };

  const runItem = (item: Internal) => {
    // A stale staggered start may fire after the item was cancelled, retried
    // or picked up by another pump pass: starting twice is never allowed.
    if (item.settled || item.controller !== null || item.state.phase !== "idle") {
      item.reserved = false;
      return;
    }
    // Paused between reservation and its staggered release: hold it (do not
    // abort anything) and surface the suspended queue state.
    if (item.paused) {
      item.reserved = false;
      emit();
      return;
    }
    item.reserved = false;
    const controller = new AbortController();
    item.controller = controller;
    if (options.signal) {
      if (options.signal.aborted) controller.abort();
      else options.signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
    // Remember the terminal cause: runTransfer resolves (never rejects), so
    // the last error seen is what the transfer failed with, if it failed.
    let lastError: unknown = null;
    const tracked: TransferDeps = {
      ...deps,
      requestIntent: async (input) => {
        try {
          return await deps.requestIntent(input);
        } catch (err) {
          lastError = err;
          throw err;
        }
      },
      upload: async (url, file, opts) => {
        try {
          await deps.upload(url, file, opts);
        } catch (err) {
          lastError = err;
          throw err;
        }
      },
      commit: async (id) => {
        try {
          return await deps.commit(id);
        } catch (err) {
          lastError = err;
          throw err;
        }
      },
    };
    active += 1;
    let slotReleased = false;
    item.state = { ...idleTransfer(item.file), phase: "requesting-intent" };
    emit();
    runTransfer(item.file, tracked, {
      folderId: item.folderId,
      idempotencyKey: item.idempotencyKey ?? queueItemId(),
      signal: controller.signal,
      config: options.config,
      onVerifying: () => {
        if (slotReleased) return;
        slotReleased = true;
        verifyingSlots += 1;
        pump();
      },
      onUpdate: (state) => {
        const progressOnly =
          state.phase === "uploading" && item.state.phase === "uploading";
        item.state = state;
        if (progressOnly) emitProgress();
        else emit();
      },
    })
      .catch(() => undefined)
      .finally(() => {
        item.controller = null;
        item.settled = true;
        active -= 1;
        if (slotReleased) verifyingSlots -= 1;
        adaptToOutcome(item, lastError);
        emit();
        pump();
        maybeFinish();
      });
  };

  const nextQueued = (): Internal | undefined =>
    items.find(
      (item) =>
        !item.settled &&
        item.controller === null &&
        !item.reserved &&
        !item.paused &&
        item.state.phase === "idle",
    );

  const pump = () => {
    if (schedulerPaused) {
      maybeFinish();
      return;
    }
    // Global semaphore: at most `effectiveConcurrency` files hold a slot, and
    // actives and staggered reservations share the same budget, so ten parallel
    // uploads never become ten simultaneous connection bursts.
    let immediateStarted = false;
    while (active - verifyingSlots + pendingStarts < effectiveConcurrency) {
      const item = nextQueued();
      if (!item) break;
      if (!immediateStarted || startStaggerMs <= 0) {
        immediateStarted = true;
        runItem(item);
        continue;
      }
      // Reserve the slot and start after a short delay, re-validating: the
      // item may have been cancelled, paused or retried in the meantime. The
      // release runs on sleep success and failure alike so a throwing sleep
      // cannot leak the reserved slot.
      item.reserved = true;
      pendingStarts += 1;
      const release = () => {
        pendingStarts -= 1;
        runItem(item);
        // runItem may have bailed (paused/settled): re-pump so the freed slot
        // is not wasted on a file that will never start.
        pump();
      };
      void Promise.resolve()
        .then(() => deps.sleep(startStaggerMs))
        .then(release, release);
    }
    maybeFinish();
  };

  // --- pause / resume -----------------------------------------------------
  // Pausing is a scheduling concern: an in-flight PUT is never aborted (there
  // is no resumable multipart yet), so suspending only prevents files that have
  // not started from starting. A paused file keeps `state.phase === "idle"` and
  // is reported through the distinct `paused` queue fields, never as `failed`.
  const markPaused = (item: Internal): void => {
    if (item.settled || item.controller !== null) return;
    item.paused = true;
  };

  const markResumed = (item: Internal): void => {
    // A reserved file is restarted by its own staggered release once the flag
    // is cleared; a held one is picked up by the next pump pass.
    item.paused = false;
  };

  const pauseAll = (): void => {
    schedulerPaused = true;
    for (const item of items) markPaused(item);
    emit();
    maybeFinish();
  };

  const resumeAll = (): void => {
    schedulerPaused = false;
    for (const item of items) markResumed(item);
    emit();
    pump();
  };

  /**
   * Put back every file that stopped on a transient error (network drop, 5xx,
   * renewed upload URL). This is what makes a cut recoverable without a click:
   * the `online` event calls it, and the manual "Réessayer" button calls the
   * broader `retryFailed`. Fatal rejections and cancellations never come back
   * on their own, and a per-file cap bounds the automatic attempts.
   */
  const retryTransient = (): void => {
    let requeued = 0;
    for (const item of items) {
      if (item.state.phase !== "failed") continue;
      if (item.state.failureKind !== "retryable") continue;
      if (item.reconnectRetries >= maxReconnectRetries) continue;
      item.reconnectRetries += 1;
      item.state = idleTransfer(item.file);
      item.settled = false;
      item.reserved = false;
      item.paused = false;
      requeued += 1;
    }
    if (requeued === 0) {
      // Nothing left to replay (fatal failures only, or the cap is reached):
      // stop holding the window listeners for a link that will not help.
      if (!awaitingReconnect() && active === 0 && items.every((item) => item.settled)) {
        detachListeners();
      }
      return;
    }
    finished = false;
    emit();
    pump();
    options.onAutoRetry?.(requeued);
  };

  // --- browser-lifecycle wiring (no setInterval anywhere) ------------------
  // Progress comes from XHR `upload.onprogress` events and the queue is driven
  // by promise continuations, so a background tab keeps making progress and
  // never depends on a polling timer. A hard navigation/reload is guarded while
  // files are in flight, and a connectivity loss suspends (not fails) the queue.
  const hasWindow = typeof window !== "undefined";
  let listenersAttached = false;

  const onBeforeUnload = (event: BeforeUnloadEvent): void => {
    if (active > 0) {
      event.preventDefault();
      // Legacy contract: a truthy returnValue triggers the browser prompt.
      event.returnValue = "";
    }
  };
  const onOffline = (): void => pauseAll();
  const onOnline = (): void => {
    if (autoPauseOnOffline) resumeAll();
    if (autoRetryOnReconnect) retryTransient();
  };

  const attachListeners = (): void => {
    if (!hasWindow || listenersAttached) return;
    listenersAttached = true;
    window.addEventListener("beforeunload", onBeforeUnload);
    if (autoPauseOnOffline) window.addEventListener("offline", onOffline);
    // The `online` listener also drives the automatic replay of transient
    // failures, so it is attached even when the queue is not auto-pausing.
    if (autoPauseOnOffline || autoRetryOnReconnect) {
      window.addEventListener("online", onOnline);
    }
  };

  const detachListeners = (): void => {
    if (!hasWindow || !listenersAttached) return;
    listenersAttached = false;
    window.removeEventListener("beforeunload", onBeforeUnload);
    window.removeEventListener("offline", onOffline);
    window.removeEventListener("online", onOnline);
  };

  attachListeners();
  if (
    hasWindow &&
    autoPauseOnOffline &&
    typeof navigator !== "undefined" &&
    navigator.onLine === false
  ) {
    // Opened while already offline: start suspended instead of racing failures.
    pauseAll();
  }

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
    pauseItem(id: string) {
      const item = items.find((candidate) => candidate.id === id);
      if (!item || item.settled) return;
      markPaused(item);
      emit();
      maybeFinish();
    },
    resumeItem(id: string) {
      const item = items.find((candidate) => candidate.id === id);
      if (!item || item.settled) return;
      markResumed(item);
      emit();
      pump();
    },
    pauseAll,
    resumeAll,
    retryTransient,
    retryFailed() {
      let requeued = false;
      for (const item of items) {
        if (item.state.phase === "failed" || item.state.phase === "cancelled") {
          item.state = idleTransfer(item.file);
          item.settled = false;
          item.reserved = false;
          item.paused = false;
          item.reconnectRetries = 0;
          requeued = true;
        }
      }
      if (!requeued) return;
      finished = false;
      emit();
      pump();
    },
    retryItem(id: string) {
      const item = items.find((candidate) => candidate.id === id);
      // Only a failed or cancelled file can restart: active items keep
      // their controller (cancel first), queued items run in turn, and
      // successes stay untouched.
      if (!item || item.controller !== null) return;
      if (item.state.phase !== "failed" && item.state.phase !== "cancelled") return;
      item.reconnectRetries = 0;
      item.state = idleTransfer(item.file);
      item.settled = false;
      item.reserved = false;
      item.paused = false;
      finished = false;
      emit();
      pump();
    },
    dispose() {
      detachListeners();
    },
    done,
  };
}
