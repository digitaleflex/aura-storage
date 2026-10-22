/**
 * Content types the API will serve inline (mirror of PREVIEWABLE_CONTENT_TYPES
 * in api/main.py). This only decides whether to offer "Aperçu"; the API stays
 * authoritative and answers 415 for anything else.
 */
const PREVIEWABLE = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/avif",
  "application/pdf",
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
  "text/plain",
  "text/csv",
  "text/tab-separated-values",
  "text/markdown",
  "application/json",
]);

export type PreviewKind = "image" | "audio" | "pdf" | "video" | "text";

/** How a text-family file is shown: a table, indented JSON, or plain text. */
export type TextFlavor = "csv" | "json" | "plain";

export function textFlavor(contentType: string | undefined): TextFlavor {
  const type = baseType(contentType);
  if (type === "application/json") return "json";
  if (type === "text/csv" || type === "text/tab-separated-values") return "csv";
  return "plain";
}

function baseType(contentType: string | undefined): string {
  return (contentType ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
}

export function isPreviewable(contentType: string | undefined): boolean {
  return PREVIEWABLE.has(baseType(contentType));
}

export function previewKind(contentType: string | undefined): PreviewKind | null {
  const type = baseType(contentType);
  if (!PREVIEWABLE.has(type)) return null;
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("audio/")) return "audio";
  if (type.startsWith("video/")) return "video";
  if (type.startsWith("text/") || type === "application/json") return "text";
  return "pdf";
}
