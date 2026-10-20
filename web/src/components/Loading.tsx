import { useEffect, useState } from "react";
import { describeError } from "../lib/errors";

/**
 * Waiting indicator: a spinner and what is being loaded, then — if it takes
 * longer than usual — a second line saying so, so nobody wonders whether the
 * page froze.
 */
export function Loading({
  label,
  slowAfterMs = 4000,
  slowHint = "C'est plus long que d'habitude, merci de patienter…",
}: {
  label: string;
  slowAfterMs?: number;
  slowHint?: string;
}) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), slowAfterMs);
    return () => window.clearTimeout(timer);
  }, [slowAfterMs]);
  return (
    <div role="status" className="loading">
      <span className="spinner" aria-hidden="true" />
      <span>{label}…</span>
      {slow ? <span className="loading-slow">{slowHint}</span> : null}
    </div>
  );
}

/** A load that failed: what failed, why in plain words, and a retry. */
export function LoadError({
  message,
  error,
  onRetry,
  retrying = false,
}: {
  message: string;
  error: unknown;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return (
    <div role="alert" className="alert alert-error load-error">
      <span>
        <strong>{message}</strong> {describeError(error, "")}
      </span>
      {onRetry ? (
        <button
          type="button"
          className="btn btn-small"
          disabled={retrying}
          onClick={onRetry}
        >
          {retrying ? <span className="spinner" aria-hidden="true" /> : null}
          {retrying ? "Nouvel essai…" : "Réessayer"}
        </button>
      ) : null}
    </div>
  );
}
