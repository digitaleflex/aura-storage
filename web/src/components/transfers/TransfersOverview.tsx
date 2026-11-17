import { useMemo } from "react";
import type { QueueState } from "../../lib/transfer";
import {
  bytesPercent,
  countTransfers,
  estimatedRemainingSeconds,
  scopeBytes,
} from "./model";
import { TransferIcon } from "./TransferIcon";
import type { TransferIconName } from "./TransferIcon";
import {
  formatBytes,
  formatDuration,
  formatRate,
  formatRemaining,
} from "../../lib/format";

interface LiveStat {
  key: string;
  label: string;
  value: string;
  tone: "muted" | "success" | "info" | "warning" | "danger";
  icon: TransferIconName;
}

/**
 * Live console band: the one thing to read at a glance is the current rate.
 * Everything else — state, volume, ETA and operational counters — stays in the
 * same band so the eye never has to jump between a ring and a grid of tiles.
 * Every figure comes from the live queue snapshot; nothing is simulated.
 */
export function TransfersOverview({
  queue,
  throughput,
  rateHistory,
  smoothedThroughput,
  startedAt,
  finishedAt,
  now,
}: {
  queue: QueueState;
  throughput: number;
  rateHistory: readonly number[];
  smoothedThroughput: number;
  startedAt: number | null;
  finishedAt: number | null;
  now: number;
}) {
  const counts = useMemo(() => countTransfers(queue), [queue]);
  const { totalBytes, transferredBytes } = useMemo(() => scopeBytes(queue), [queue]);
  const volumePercent = bytesPercent(totalBytes, transferredBytes);
  const etaRate = smoothedThroughput > 0 ? smoothedThroughput : 0;
  const remainingSeconds = estimatedRemainingSeconds(queue, etaRate);
  const unstable =
    throughput > 0 &&
    smoothedThroughput > 0 &&
    Math.abs(throughput - smoothedThroughput) / smoothedThroughput > 0.75;
  const elapsedSeconds =
    startedAt !== null
      ? Math.max(0, ((finishedAt ?? now) - startedAt) / 1000)
      : 0;
  const averageRate =
    startedAt !== null && elapsedSeconds >= 1
      ? transferredBytes / elapsedSeconds
      : 0;

  const title = (() => {
    if (counts.total === 0) return "Aucune importation en cours";
    if (queue.schedulerPaused) return "Importation en pause";
    if (queue.finished) {
      if (counts.completed === 0 && counts.failed === 0 && counts.cancelled > 0) {
        return "Importation annulée";
      }
      if (counts.failed > 0 && counts.completed > 0) {
        return "Importation terminée avec des échecs";
      }
      if (counts.failed > 0) return "Importation en échec";
      return "Importation terminée";
    }
    return "Importation en cours";
  })();

  const rateValue =
    throughput > 0
      ? formatRate(throughput)
      : counts.active > 0
        ? "Calcul en cours"
        : "Inactif";

  const etaValue = (() => {
    if (remainingSeconds !== null) {
      return unstable ? "Estimation instable" : formatRemaining(remainingSeconds);
    }
    if (counts.total > 0 && !queue.finished && !queue.schedulerPaused) {
      return counts.active > 0 ? "Calcul en cours" : "Indisponible";
    }
    if (queue.schedulerPaused && counts.total > 0) return "En pause";
    return "—";
  })();

  const stats: LiveStat[] = [
    { key: "eta", label: "Temps restant", value: etaValue, tone: "muted", icon: "clock" },
    {
      key: "active",
      label: "Actifs",
      value: String(counts.active),
      tone: "info",
      icon: "queue",
    },
    {
      key: "completed",
      label: "Terminés",
      value: String(counts.completed),
      tone: "success",
      icon: "check",
    },
    {
      key: "queued",
      label: "En attente",
      value: String(counts.queued),
      tone: "warning",
      icon: "clock",
    },
    {
      key: "failed",
      label: "En échec",
      value: String(counts.failed),
      tone: "danger",
      icon: "alert",
    },
  ];

  return (
    <section
      className="transfers-live"
      aria-labelledby="transfers-overview-title"
      data-testid="transfer-overview"
    >
      <div className="transfers-live-top">
        <div className="transfers-live-copy">
          <p className="transfers-live-kicker">Session courante · temps réel</p>
          <h2 id="transfers-overview-title">{title}</h2>
          <p className="transfers-overview-files">
            {counts.completed} sur {counts.denominator} fichiers terminés
            {counts.paused > 0 ? ` · ${counts.paused} en pause` : ""}
          </p>
        </div>

        <div className="transfers-live-rate">
          <span className="transfers-live-rate-label">Débit actuel</span>
          <strong className="transfers-live-rate-value">{rateValue}</strong>
          {rateHistory.length > 1 ? <RateSparkline values={rateHistory} /> : null}
        </div>
      </div>

      <div className="transfers-live-progress">
        <div
          className="transfers-volume-bar"
          role="progressbar"
          aria-label="Progression du volume transféré"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={volumePercent}
          aria-valuetext={`${volumePercent} %`}
        >
          <span
            className="transfers-volume-fill"
            style={{ width: `${volumePercent}%` }}
          />
        </div>
        <div className="transfers-live-progress-meta">
          <p className="transfers-overview-volume">
            {formatBytes(transferredBytes)} sur {formatBytes(totalBytes)} transférés
          </p>
          {counts.total > 0 && startedAt !== null ? (
            <p className="transfers-overview-timing">
              Durée {formatDuration(elapsedSeconds)} · Débit moyen {formatRate(averageRate)}
            </p>
          ) : null}
          <p className="transfers-overview-hint">
            {counts.cancelled > 0
              ? `${counts.cancelled} fichier${counts.cancelled > 1 ? "s" : ""} annulé${
                  counts.cancelled > 1 ? "s" : ""
                } exclu${counts.cancelled > 1 ? "s" : ""} du total.`
              : "Suivi de la session de navigateur en cours."}
          </p>
        </div>
      </div>

      <div className="transfers-live-stats" data-testid="transfer-metrics">
        {stats.map((stat) => (
          <div
            key={stat.key}
            className={`transfers-live-stat transfers-live-stat--${stat.tone}`}
          >
            <span className="transfers-live-stat-icon" aria-hidden="true">
              <TransferIcon name={stat.icon} size={15} />
            </span>
            <span className="transfers-live-stat-label">{stat.label}</span>
            <span className="transfers-live-stat-value">{stat.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Last-60-second rate trend rendered beside the live rate figure. */
function RateSparkline({ values }: { values: readonly number[] }) {
  const max = Math.max(...values, 1);
  const width = 100;
  const height = 28;
  const padding = 2;
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y =
        height - padding - (Math.max(value, 0) / max) * (height - padding * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className="transfers-sparkline"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Débit global sur les ${values.length} dernières secondes`}
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
