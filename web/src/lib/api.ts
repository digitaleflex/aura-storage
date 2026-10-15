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
  /** Folder the object is filed in, or null when unfiled. */
  folder_id: string | null;
}

export interface ObjectsListResponse {
  items: ObjectItem[];
}

/** A logical folder owned by the signed-in human user (#61). */
export interface FolderItem {
  id: string;
  name: string;
  parent_id: string | null;
  created_at: number;
}

export interface FolderCreateInput {
  name: string;
  parent_id?: string | null;
}

export interface FolderPatchInput {
  name?: string;
  parent_id?: string | null;
}

/** Response of creating a machine identity: the token is shown exactly once. */
export interface IdentityCreateResponse {
  id: string;
  name: string;
  space_id: string;
  application_id: string;
  scopes: string[];
  expires_at: number | null;
  token: string;
}

export interface IdentityRotateResponse {
  id: string;
  token: string;
}

export interface ReconcileResponse {
  expired: number;
  storage_deletes_attempted: number;
}

/**
 * Mirrors `SERVICE_SCOPES` in api/authz.py: machine identities are data-plane
 * principals and may never hold platform administration capabilities.
 */
export const SERVICE_SCOPES = [
  "objects:read",
  "objects:write",
  "objects:delete",
  "objects:purge",
] as const;

export interface UploadIntentRequest {
  /**
   * Optional: when omitted the server files the object in the caller's default
   * space bucket. Only sent when a caller must target a specific bucket.
   */
  bucket?: string;
  display_name: string;
  content_type: string;
  /** Exact object size in bytes; the API signs it into the presigned URL. */
  size_bytes: number;
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

/** Principal metadata returned by GET /api/v1/me. */
export interface SessionInfo {
  id: string;
  /** "user" (human session) or "service" (machine identity). */
  kind: string;
  /** Role for humans: "user" | "operator" | "admin"; null for services. */
  role: string | null;
  space_id: string | null;
  application_id: string | null;
  scopes: string[];
}

/** True when a role may read the administration console (`admin:read`). */
export function hasAdminAccess(role: string | null | undefined): boolean {
  return role === "operator" || role === "admin";
}

/** True when a machine identity scope list contains `scope`. */
export function hasScope(
  scopes: readonly string[] | null | undefined,
  scope: string,
): boolean {
  return scopes?.includes(scope) ?? false;
}

export interface AdminStats {
  objects_by_status: Record<string, number>;
  applications: number;
  spaces: number;
  buckets: number;
  service_identities: number;
  active_service_identities: number;
}

export interface ApplicationItem {
  id: string;
  name: string;
  status: string;
}

export interface SpaceItem {
  id: string;
  application_id: string;
  name: string;
  environment: string;
}

export interface IdentityItem {
  id: string;
  name: string;
  space_id: string;
  application_id: string;
  scopes: string[];
  created_at: number;
  expires_at: number | null;
  last_used_at: number | null;
  revoked_at: number | null;
  rotated_at: number | null;
}

export interface ListResponse<T> {
  items: T[];
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

  /**
   * List objects. `folderId` narrows the list against the catalogue:
   * `undefined` = every object, `null` = only unfiled objects, a string = that
   * folder. The folder id is validated by the server.
   */
  listObjects(folderId?: string | null): Promise<ObjectsListResponse> {
    let path = "/api/v1/objects";
    if (folderId !== undefined) {
      const value = folderId ?? "root";
      path += `?folder_id=${encodeURIComponent(value)}`;
    }
    return request<ObjectsListResponse>(path);
  },

  me(): Promise<SessionInfo> {
    return request<SessionInfo>("/api/v1/me");
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

  // --- Object lifecycle ---
  /** Soft-delete an object (objects:delete). */
  deleteObject(id: string, csrf: string): Promise<{ id: string; status: string }> {
    return request<{ id: string; status: string }>(
      `/api/v1/objects/${encodeURIComponent(id)}`,
      { method: "DELETE", csrf },
    );
  },

  /** Permanently delete an object (objects:purge; operator/admin only). */
  purgeObject(id: string, csrf: string): Promise<{ id: string; status: string }> {
    return request<{ id: string; status: string }>(
      `/api/v1/objects/${encodeURIComponent(id)}/purge`,
      { method: "POST", csrf },
    );
  },

  // --- Logical folders (human session only) ---
  listFolders(parentId?: string): Promise<ListResponse<FolderItem>> {
    const path = parentId
      ? `/api/v1/folders?parent_id=${encodeURIComponent(parentId)}`
      : "/api/v1/folders";
    return request<ListResponse<FolderItem>>(path);
  },

  getFolder(id: string): Promise<FolderItem> {
    return request<FolderItem>(`/api/v1/folders/${encodeURIComponent(id)}`);
  },

  createFolder(input: FolderCreateInput, csrf: string): Promise<FolderItem> {
    return request<FolderItem>("/api/v1/folders", {
      method: "POST",
      body: input,
      csrf,
    });
  },

  updateFolder(id: string, patch: FolderPatchInput, csrf: string): Promise<FolderItem> {
    return request<FolderItem>(`/api/v1/folders/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: patch,
      csrf,
    });
  },

  deleteFolder(id: string, csrf: string): Promise<{ id: string; status: string }> {
    return request<{ id: string; status: string }>(
      `/api/v1/folders/${encodeURIComponent(id)}`,
      { method: "DELETE", csrf },
    );
  },

  // --- Administration console (read-only, `admin:read`) ---
  adminStats(): Promise<AdminStats> {
    return request<AdminStats>("/api/v1/admin/stats");
  },

  listApplications(): Promise<ListResponse<ApplicationItem>> {
    return request<ListResponse<ApplicationItem>>("/api/v1/admin/applications");
  },

  listSpaces(): Promise<ListResponse<SpaceItem>> {
    return request<ListResponse<SpaceItem>>("/api/v1/admin/spaces");
  },

  listIdentities(): Promise<ListResponse<IdentityItem>> {
    return request<ListResponse<IdentityItem>>("/api/v1/admin/identities");
  },

  // --- Administration mutations (`admin:write`) ---
  reconcile(csrf: string): Promise<ReconcileResponse> {
    return request<ReconcileResponse>("/api/v1/admin/reconcile", {
      method: "POST",
      csrf,
    });
  },

  createApplication(
    name: string,
    csrf: string,
  ): Promise<{ id: string; name: string }> {
    return request<{ id: string; name: string }>("/api/v1/admin/applications", {
      method: "POST",
      body: { name },
      csrf,
    });
  },

  createSpace(
    input: {
      application_id: string;
      name: string;
      environment: string;
      default_bucket?: string;
    },
    csrf: string,
  ): Promise<{ id: string; bucket: string }> {
    return request<{ id: string; bucket: string }>("/api/v1/admin/spaces", {
      method: "POST",
      body: input,
      csrf,
    });
  },

  createIdentity(
    input: {
      space_id: string;
      name: string;
      scopes: string[];
      ttl_seconds?: number;
    },
    csrf: string,
  ): Promise<IdentityCreateResponse> {
    return request<IdentityCreateResponse>("/api/v1/admin/identities", {
      method: "POST",
      body: input,
      csrf,
    });
  },

  rotateIdentity(id: string, csrf: string): Promise<IdentityRotateResponse> {
    return request<IdentityRotateResponse>(
      `/api/v1/admin/identities/${encodeURIComponent(id)}/rotate`,
      { method: "POST", csrf },
    );
  },

  revokeIdentity(id: string, csrf: string): Promise<{ id: string; revoked: boolean }> {
    return request<{ id: string; revoked: boolean }>(
      `/api/v1/admin/identities/${encodeURIComponent(id)}/revoke`,
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
