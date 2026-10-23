import { useMemo } from "react";
import type { QueueState } from "../../lib/transfer";
import {
  bytesPercent,
  countTransfers,
  estimatedRemainingSeconds,
  filesPercent,
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

const RING_SIZE = 132;
const RING_STROKE = 9;
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

interface Metric {
  key: string;
  label: string;
  value: string;
  tone: "primary" | "success" | "info" | "warning" | "danger" | "muted";
  icon: TransferIconName;
}

/**
 * Session summary: where the import stands (files + volume), how fast it runs,
 * what remains, and how many files sit in each operational bucket. Every figure
 * comes from the live queue snapshot; nothing is simulated.
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
  const filePercent = filesPercent(counts);
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

  const metrics: Metric[] = [
    { key: "rate", label: "Débit actuel", value: rateValue, tone: "primary", icon: "gauge" },
    { key: "eta", label: "Temps restant", value: etaValue, tone: "muted", icon: "clock" },
    {
      key: "active",
      label: "Transferts actifs",
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

  const dashOffset = RING_CIRCUMFERENCE * (1 - filePercent / 100);

  return (
    <section
      className="transfers-overview"
      aria-labelledby="transfers-overview-title"
      data-testid="transfer-overview"
    >
      <div className="transfers-overview-main">
        <div
          className="transfers-ring"
          role="img"
          aria-label={`${filePercent} % des fichiers terminés`}
        >
          <svg width={RING_SIZE} height={RING_SIZE} viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`} aria-hidden="true">
            <circle
              className="transfers-ring-track"
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={RING_RADIUS}
              fill="none"
              strokeWidth={RING_STROKE}
            />
            <circle
              className="transfers-ring-value"
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={RING_RADIUS}
              fill="none"
              strokeWidth={RING_STROKE}
              strokeLinecap="round"
              strokeDasharray={RING_CIRCUMFERENCE}
              strokeDashoffset={dashOffset}
              transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
            />
          </svg>
          <span className="transfers-ring-label">{filePercent} %</span>
        </div>

        <div className="transfers-overview-copy">
          <h2 id="transfers-overview-title">{title}</h2>
          <p className="transfers-overview-files">
            {counts.completed} sur {counts.denominator} fichiers terminés
            {counts.paused > 0 ? ` · ${counts.paused} en pause` : ""}
          </p>
          <p className="transfers-overview-volume">
            {formatBytes(transferredBytes)} sur {formatBytes(totalBytes)} transférés
          </p>
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
          {counts.total > 0 && startedAt !== null ? (
            <p className="transfers-overview-timing">
              Durée {formatDuration(elapsedSeconds)} · Débit moyen{" "}
              {formatRate(averageRate)}
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

      <div className="transfers-metrics" data-testid="transfer-metrics">
        {metrics.map((metric) => (
          <div
            key={metric.key}
            className={`transfers-metric transfers-metric--${metric.tone}`}
          >
            <span className="transfers-metric-icon" aria-hidden="true">
              <TransferIcon name={metric.icon} size={17} />
            </span>
            <span className="transfers-metric-label">{metric.label}</span>
            <span className="transfers-metric-value">{metric.value}</span>
            {metric.key === "rate" && rateHistory.length > 1 ? (
              <RateSparkline values={rateHistory} />
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

/** Last-60-second rate trend rendered inside the "Débit actuel" tile. */
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
