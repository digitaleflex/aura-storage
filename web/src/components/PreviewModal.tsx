import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { ObjectItem, PreviewIntentResponse } from "../lib/api";

/**
 * Above this size the browser is doing real work to render the media; we warn
 * before attempting it instead of silently pulling tens of megabytes.
 */
const PREVIEW_WARN_BYTES = 50 * 1024 * 1024;

type PreviewKind = "image" | "audio" | "pdf" | "other";

/** Which inline element (if any) can render this media type. */
function previewKind(contentType: string | undefined): PreviewKind {
  const value = (contentType ?? "").toLowerCase();
  if (value.startsWith("image/")) return "image";
  if (value.startsWith("audio/")) return "audio";
  if (value === "application/pdf") return "pdf";
  return "other";
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return "taille inconnue";
  if (size === 0) return "0 o";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  const index = Math.min(
    Math.floor(Math.log(size) / Math.log(1024)),
    units.length - 1,
  );
  const value = size / 1024 ** index;
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

type Status = "idle" | "loading" | "ready" | "error";

/**
 * Accessible inline preview. Built on the native <dialog> so Escape closes it
 * and focus is trapped while it is open. The media source is the short-lived
 * presigned URL returned by the API and is used directly (never turned into a
 * blob); the URL is never logged.
 *
 * Degraded mode: when the preview endpoint is missing the API returns a
 * download intent (`fallback`), whose URL may force a download and therefore
 * cannot reliably render inline — we then offer the download instead of showing
 * a broken frame.
 */
export function PreviewModal({
  item,
  csrf,
  onClose,
  onDownload,
}: {
  item: ObjectItem | null;
  csrf: string | null;
  onClose: () => void;
  onDownload: (item: ObjectItem) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [intent, setIntent] = useState<PreviewIntentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const open = item !== null;

  // Keep the native dialog in sync with the controlled `open` state.
  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open]);

  // Mint a fresh preview intent each time a new object is opened.
  useEffect(() => {
    if (!item) return;
    if (!csrf) {
      setStatus("error");
      setIntent(null);
      setError("Session expirée. Reconnectez-vous.");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    setIntent(null);
    setError(null);
    api.createPreviewIntent(item.id, csrf).then(
      (result) => {
        if (cancelled) return;
        setIntent(result);
        setStatus("ready");
      },
      (err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? `Aperçu indisponible : ${err.detail}`
            : "Aperçu indisponible.",
        );
        setStatus("error");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [item, csrf]);

  const kind = previewKind(intent?.content_type ?? item?.content_type);
  const sizeBytes = intent?.size_bytes ?? item?.size_bytes ?? 0;
  const oversized = sizeBytes > PREVIEW_WARN_BYTES;
  const renderable = status === "ready" && intent !== null && !intent.fallback;
  const canRender = renderable && kind !== "other";

  return (
    <dialog
      ref={dialogRef}
      className="dialog preview-dialog"
      onClose={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="preview-title"
    >
      <div className="dialog-head">
        <h2 id="preview-title">
          {item ? `Aperçu — ${item.display_name}` : "Aperçu"}
        </h2>
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={onClose}
          aria-label="Fermer l'aperçu"
          autoFocus
        >
          Fermer
        </button>
      </div>
      <div className="dialog-body preview-body">
        {status === "loading" ? (
          <p className="muted" role="status">
            Chargement de l'aperçu…
          </p>
        ) : null}

        {status === "error" ? (
          <p role="alert" className="alert alert-error">
            {error}
          </p>
        ) : null}

        {status === "ready" && item ? (
          <>
            {oversized ? (
              <p role="status" className="alert preview-warn">
                Fichier volumineux ({formatBytes(sizeBytes)}) : l'aperçu peut
                solliciter fortement le navigateur.
              </p>
            ) : null}

            {canRender && intent ? (
              kind === "image" ? (
                <img
                  className="preview-media"
                  src={intent.preview_url}
                  alt={`Aperçu de ${item.display_name}`}
                />
              ) : kind === "audio" ? (
                <audio
                  className="preview-audio"
                  src={intent.preview_url}
                  controls
                  preload="metadata"
                >
                  Votre navigateur ne peut pas lire cet audio.
                </audio>
              ) : (
                <iframe
                  className="preview-frame"
                  src={intent.preview_url}
                  title={`Aperçu PDF de ${item.display_name}`}
                />
              )
            ) : (
              <div className="preview-fallback">
                <p className="muted">
                  {intent?.fallback
                    ? "Ce serveur n'expose pas l'aperçu en ligne. Téléchargez le fichier pour le consulter."
                    : "Ce type de fichier ne peut pas être affiché dans le navigateur."}
                </p>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => onDownload(item)}
                >
                  Télécharger
                </button>
              </div>
            )}
          </>
        ) : null}
      </div>
    </dialog>
  );
}
