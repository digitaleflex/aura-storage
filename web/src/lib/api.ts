/**
 * Typed client for the AURA Management API.
 *
 * Security rules enforced here:
 * - Session is carried by the HttpOnly `aura_session` cookie
 *   (`credentials: "include"`); the app never sees or stores it.
 * - Mutations send the CSRF token in the `x-csrf-token` header.
 * - No S3 credentials exist in this bundle. Presigned URLs are opaque
 *   short-lived strings issued by the API; uploads PUT bytes to them.
 * - Only relative paths are used, so no backend address leaks into the UI.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface LoginResponse {
  csrf_token: string;
}

export interface ObjectItem {
  id: string;
  display_name: string;
  content_type: string;
  size_bytes: number;
  checksum_sha256: string;
  status: string;
}

export interface ObjectsListResponse {
  items: ObjectItem[];
}

export interface UploadIntentRequest {
  bucket: string;
  display_name: string;
  content_type: string;
  folder_id?: string | null;
}

export interface UploadIntentResponse {
  id: string;
  upload_url: string;
  expires_in: number;
}

export interface CommitResponse {
  id: string;
  status: string;
  size_bytes: number;
  checksum_sha256: string;
}

export interface DownloadIntentResponse {
  download_url: string;
  expires_in: number;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  csrf?: string | null;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  if (options.csrf) {
    headers["x-csrf-token"] = options.csrf;
  }
  const res = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body,
    credentials: "include",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string" && data.detail.length > 0) {
        detail = data.detail;
      }
    } catch {
      // Keep the HTTP status text when the body is not JSON.
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  login(username: string, password: string): Promise<LoginResponse> {
    return request<LoginResponse>("/api/v1/login", {
      method: "POST",
      body: { username, password },
    });
  },

  logout(csrf: string): Promise<{ status: string }> {
    return request<{ status: string }>("/api/v1/logout", {
      method: "POST",
      csrf,
    });
  },

  listObjects(): Promise<ObjectsListResponse> {
    return request<ObjectsListResponse>("/api/v1/objects");
  },

  getObject(id: string): Promise<ObjectItem> {
    return request<ObjectItem>(`/api/v1/objects/${encodeURIComponent(id)}`);
  },

  createUploadIntent(input: UploadIntentRequest, csrf: string): Promise<UploadIntentResponse> {
    return request<UploadIntentResponse>("/api/v1/objects/upload-intents", {
      method: "POST",
      body: input,
      csrf,
    });
  },

  commitObject(id: string, csrf: string): Promise<CommitResponse> {
    return request<CommitResponse>(`/api/v1/objects/${encodeURIComponent(id)}/commit`, {
      method: "POST",
      csrf,
    });
  },

  createDownloadIntent(id: string, csrf: string): Promise<DownloadIntentResponse> {
    return request<DownloadIntentResponse>(
      `/api/v1/objects/${encodeURIComponent(id)}/download-intent`,
      { method: "POST", csrf },
    );
  },
};

/** PUT file bytes to the short-lived URL issued by the upload intent. */
export async function putToPresignedUrl(url: string, file: File): Promise<void> {
  const res = await fetch(url, {
    method: "PUT",
    headers: { "content-type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!res.ok) {
    throw new Error(`Presigned upload failed (HTTP ${res.status}).`);
  }
}
