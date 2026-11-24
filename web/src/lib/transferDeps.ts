import { api, putToPresignedUrl } from "./api";
import type { TransferDeps } from "./transfer";

/**
 * Control-plane calls are small and quick: a hung one must free its queue slot
 * instead of holding it. The commit is the exception — the API deliberately
 * spends up to 300 s hashing, under a 310 s proxy deadline, so give it margin.
 */
const CONTROL_TIMEOUT_MS = 60_000;
const COMMIT_TIMEOUT_MS = 330_000;

/**
 * Wire the transfer engine to the real API for one authenticated session.
 *
 * The engine stays dependency-injected (see `lib/transfer.ts`): this module is
 * the only place that knows the REST endpoints, so the same queue can be
 * driven by the files page and read by the transfers page without duplicating
 * network logic.
 */
export function transferDeps(
  activeCsrf: string,
  /** Client UUID grouping every intent of this page-load/import session. */
  transferSessionId?: string,
): TransferDeps {
  return {
    requestIntent: (input) =>
      api.createUploadIntent(
        {
          display_name: input.fileName,
          content_type: input.contentType,
          size_bytes: input.sizeBytes,
          folder_id: input.folderId,
          ...(transferSessionId
            ? { transfer_session_id: transferSessionId }
            : {}),
        },
        activeCsrf,
        { idempotencyKey: input.idempotencyKey, timeoutMs: CONTROL_TIMEOUT_MS },
      ),
    requestReplaceIntent: (targetId, input) =>
      api.createReplaceIntent(
        targetId,
        {
          display_name: input.fileName,
          content_type: input.contentType,
          size_bytes: input.sizeBytes,
          folder_id: input.folderId,
          ...(transferSessionId
            ? { transfer_session_id: transferSessionId }
            : {}),
        },
        activeCsrf,
        { idempotencyKey: input.idempotencyKey, timeoutMs: CONTROL_TIMEOUT_MS },
      ),
    upload: (url, selected, opts) =>
      putToPresignedUrl(url, selected, {
        headers: opts.headers,
        onProgress: opts.onProgress,
        signal: opts.signal,
      }),
    commit: (id) => api.commitObject(id, activeCsrf, COMMIT_TIMEOUT_MS),
    multipartStatus: (id) => api.multipartStatus(id, CONTROL_TIMEOUT_MS),
    objectStatus: (id) => api.getObject(id, CONTROL_TIMEOUT_MS),
    partUrls: (id, numbers) => api.multipartPartUrls(id, numbers, activeCsrf, CONTROL_TIMEOUT_MS),
    abortIntent: async (id) => {
      await api.abortObject(id, activeCsrf, CONTROL_TIMEOUT_MS);
    },
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    random: Math.random,
  };
}
