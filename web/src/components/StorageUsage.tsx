import type { UsageResponse } from "../lib/api";

/**
 * Sidebar storage indicator.
 *
 * It only ever shows the real admin figure (`GET /admin/usage`). When no
 * capacity is configured, the consumed volume is shown without inventing a
 * total or a percentage; for accounts without access, the honest encryption
 * statement is kept instead of a fabricated gauge.
 */
export function StorageUsage({
  usage,
  loading = false,
  formatBytes,
}: {
  usage?: UsageResponse | null;
  loading?: boolean;
  formatBytes: (size: number) => string;
}) {
  const capacity = usage?.capacity ?? null;
  const storedBytes = capacity?.stored_bytes ?? usage?.totals.stored_bytes ?? 0;
  const capacityBytes = capacity?.capacity_bytes ?? 0;
  const percent =
    capacity && capacityBytes > 0
      ? Math.max(0, Math.min(100, Math.round((storedBytes / capacityBytes) * 100)))
      : null;

  return (
    <div className="sidebar-foot storage-usage">
      <svg
        aria-hidden="true"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <rect x="5" y="11" width="14" height="10" rx="2" />
        <path d="M8 11V8a4 4 0 0 1 8 0v3" />
      </svg>
      {loading ? (
        <span className="storage-usage-empty">Stockage : chargement…</span>
      ) : usage ? (
        <div className="storage-usage-body">
          <span className="storage-usage-label">Stockage utilisé</span>
          <span className="storage-usage-values" aria-live="polite" aria-atomic="true">
            {formatBytes(storedBytes)}
            {capacity ? ` / ${formatBytes(capacityBytes)}` : ""}
          </span>
          {percent !== null ? (
            <>
              <div
                className="storage-usage-bar"
                role="progressbar"
                aria-label="Stockage utilisé"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
                aria-valuetext={`${percent} %`}
              >
                <span
                  className="storage-usage-fill"
                  style={{ width: `${percent}%` }}
                />
              </div>
              <span className="storage-usage-percent">{percent} %</span>
            </>
          ) : (
            <span className="storage-usage-percent storage-usage-note">
              Capacité non configurée
            </span>
          )}
        </div>
      ) : (
        <span className="storage-usage-empty">
          Chiffré au repos, intégrité vérifiée
        </span>
      )}
    </div>
  );
}
