import { api, putToPresignedUrl } from "./api";
import type { TransferDeps } from "./transfer";

/**
 * Wire the transfer engine to the real API for one authenticated session.
 *
 * The engine stays dependency-injected (see `lib/transfer.ts`): this module is
 * the only place that knows the REST endpoints, so the same queue can be
 * driven by the files page and read by the transfers page without duplicating
 * network logic.
 */
export function transferDeps(activeCsrf: string): TransferDeps {
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
    multipartStatus: (id) => api.multipartStatus(id),
    objectStatus: (id) => api.getObject(id),
    partUrls: (id, numbers) => api.multipartPartUrls(id, numbers, activeCsrf),
    abortIntent: async (id) => {
      await api.abortObject(id, activeCsrf);
    },
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    random: Math.random,
  };
}
