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
import { formatBytes, formatRate, formatRemaining } from "../../lib/format";

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
}: {
  queue: QueueState;
  throughput: number;
}) {
  const counts = useMemo(() => countTransfers(queue), [queue]);
  const { totalBytes, transferredBytes } = useMemo(() => scopeBytes(queue), [queue]);
  const filePercent = filesPercent(counts);
  const volumePercent = bytesPercent(totalBytes, transferredBytes);
  const remainingSeconds = estimatedRemainingSeconds(queue, throughput);

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
    if (remainingSeconds !== null) return formatRemaining(remainingSeconds);
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
          </div>
        ))}
      </div>
    </section>
  );
}
