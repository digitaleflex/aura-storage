import type { UsageResponse } from "../lib/api";

/**
 * At-a-glance state of the vault, from real catalogue figures only (no invented
 * metrics): space used against the configured capacity, how many files the
 * server has verified, what is still waiting, and the per-file size limit.
 */
export function VaultOverview({
  usage,
  formatBytes,
  measuredLabel,
}: {
  usage: UsageResponse | undefined;
  formatBytes: (n: number) => string;
  /** Human time of the measurement, announced to assistive technology. */
  measuredLabel: string;
}) {
  if (!usage?.totals) return null;
  const { totals, capacity, limits } = usage;
  const waiting =
    (totals.objects_by_status.pending ?? 0) + (totals.objects_by_status.verifying ?? 0);
  const pct =
    capacity && capacity.capacity_bytes > 0
      ? Math.min(100, (capacity.stored_bytes / capacity.capacity_bytes) * 100)
      : null;
  const tone =
    pct === null
      ? "ok"
      : pct >= (capacity?.high_watermark_pct ?? 90)
        ? "danger"
        : pct >= (capacity?.high_watermark_pct ?? 90) * 0.75
          ? "warn"
          : "ok";
  return (
    <section className="overview" aria-label="Synthèse du coffre" data-testid="vault-overview">
      <span className="visually-hidden">Usage réel (admin), mesuré le {measuredLabel}.</span>
      <div className="overview-tile">
        <span className="overview-label">Espace utilisé</span>
        <strong className="overview-value">{formatBytes(totals.stored_bytes)}</strong>
        {pct !== null && capacity ? (
          <>
            <div
              className={`meter meter-${tone}`}
              role="meter"
              aria-label="Espace utilisé"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(pct)}
            >
              <span style={{ width: `${Math.max(pct, 1)}%` }} />
            </div>
            <span className="overview-sub">
              {pct < 10 ? pct.toFixed(1) : Math.round(pct)} % de{" "}
              {formatBytes(capacity.capacity_bytes)}
            </span>
          </>
        ) : (
          <span className="overview-sub">Capacité non configurée</span>
        )}
      </div>
      <div className="overview-tile">
        <span className="overview-label">Fichiers vérifiés</span>
        <strong className="overview-value">{totals.available_count}</strong>
        <span className="overview-sub">Taille et SHA-256 contrôlés par le serveur</span>
      </div>
      <div className="overview-tile">
        <span className="overview-label">En attente de validation</span>
        <strong className="overview-value">{waiting}</strong>
        <span className="overview-sub">
          {waiting > 0 ? "Disponibles dès la fin du contrôle" : "Rien en attente"}
        </span>
      </div>
      <div className="overview-tile">
        <span className="overview-label">Taille maximale</span>
        <strong className="overview-value">{formatBytes(limits.max_object_bytes)}</strong>
        <span className="overview-sub">Par fichier importé</span>
      </div>
    </section>
  );
}
