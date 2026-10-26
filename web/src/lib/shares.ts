import type { ObjectShare } from "./api";

/**
 * Content types the API allows with `Content-Disposition: inline` on a share
 * link (mirror of SAFE_INLINE_TYPES in api/shares.py). Everything else -- HTML,
 * SVG, XHTML, audio, video -- is download-only on a share. The server stays
 * authoritative and answers 422 when the client gets this wrong.
 */
const SHARE_INLINE = new Set([
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "text/plain",
  "audio/mpeg",
  "audio/mp3",
  "audio/wav",
  "audio/x-wav",
  "audio/ogg",
  "audio/webm",
  "audio/mp4",
  "audio/aac",
  "audio/flac",
  "video/mp4",
  "video/webm",
  "video/ogg",
]);

function baseType(contentType: string | undefined): string {
  return (contentType ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
}

/** True when "Afficher dans le navigateur" may be offered for this type. */
export function canShareInline(contentType: string | undefined): boolean {
  return SHARE_INLINE.has(baseType(contentType));
}

/**
 * The API returns an absolute URL when AURA_SHARE_BASE_URL is configured and a
 * root-relative `/s/<token>` otherwise (it never derives the origin from the
 * request Host header). Resolve the relative form against the app origin so the
 * copied link is always usable.
 */
export function absoluteShareUrl(url: string, origin: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  const path = url.startsWith("/") ? url : `/${url}`;
  return `${origin.replace(/\/+$/, "")}${path}`;
}

export type ShareState = "active" | "revoked" | "expired" | "exhausted";

/**
 * Why a link is usable or not. The server sends an authoritative `active` flag;
 * this only names the reason for the UI, in the same precedence order.
 */
export function shareState(share: ObjectShare, now: number): ShareState {
  if (share.revoked_at !== null) return "revoked";
  if (share.expires_at <= now) return "expired";
  if (share.max_uses !== null && share.use_count >= share.max_uses) return "exhausted";
  return "active";
}

export const SHARE_STATE_LABELS: Record<ShareState, string> = {
  active: "Actif",
  revoked: "Révoqué",
  expired: "Expiré",
  exhausted: "Épuisé",
};
