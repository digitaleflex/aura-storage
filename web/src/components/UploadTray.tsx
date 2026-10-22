import { memo, useState } from "react";
import { Elapsed } from "./Elapsed";
import { FileDetail } from "./FileDetail";
import { CONCURRENCY_CHOICES } from "../lib/uploadPrefs";

/** From this size one PUT lasts many minutes on an ordinary uplink. */
const LARGE_FILE_BYTES = 500 * 1024 * 1024;
import type { QueueItem, QueueState, TransferPhase } from "../lib/transfer";

/** Which files the upload tray lists. "auto" shows everything for a small
 * batch and only what still needs attention for a big one: rendering every row
 * of a 10 000-file import costs 22-57 ms per refresh (~50k DOM nodes). */
type TrayFilter = "auto" | "active" | "failed" | "all";
const TRAY_AUTO_ALL_MAX = 30;
const TRAY_ROW_CAP = 100;

/** Human label for each transfer phase (import → validation → availability). */
const PHASE_LABEL: Record<TransferPhase, string> = {
  idle: "En attente",
  "requesting-intent": "Autorisation…",
  uploading: "Envoi…",
  validating: "Vérification d'intégrité…",
  available: "Disponible",
  failed: "Échec",
  cancelled: "Annulé",
};

/** Phases that are still moving (offer a per-file interrupt). */
const ACTIVE_PHASES: TransferPhase[] = ["requesting-intent", "uploading", "validating"];

/** Chip style for a queue item's phase. */
/** One plain-language sentence on what is happening to a file right now. */
function describeItem(item: QueueItem, waitingAhead: number): string | null {
  const st = item.state;
  switch (st.phase) {
    case "idle":
      return waitingAhead > 0
        ? `En attente d'une place dans la file (${waitingAhead} fichier${waitingAhead > 1 ? "s" : ""} avant lui).`
        : "En attente d'une place dans la file.";
    case "requesting-intent":
      return "Demande d'autorisation d'envoi au serveur.";
    case "uploading":
      return st.attempts > 0
        ? `Envoi direct vers le stockage chiffré (reprise n° ${st.attempts}).`
        : "Envoi direct vers le stockage chiffré.";
    case "validating":
      return st.verifyMode === "background"
        ? "Octets reçus. Le serveur vérifie l'intégrité (SHA-256) en tâche de fond : le fichier sera disponible ensuite, même si vous fermez la page."
        : "Octets reçus. Le serveur relit le fichier et calcule son empreinte SHA-256 avant de le publier.";
    case "failed":
      return st.failureKind === "retryable"
        ? "Interrompu par un incident réseau ou serveur : « Relancer » reprend ce fichier."
        : st.failureKind === "expired"
          ? "L'autorisation d'envoi a expiré trop de fois : « Relancer » en demande une nouvelle."
          : st.failureKind === "fatal"
            ? "Refusé par le serveur : réessayer ne changera pas le résultat sans corriger la cause."
            : null;
    case "cancelled":
      return "Annulé par vous. « Relancer » le remet dans la file.";
    default:
      return null;
  }
}

function queuePhaseClass(phase: TransferPhase): string {
  if (phase === "available") return "chip chip-ok";
  if (phase === "failed") return "chip chip-error";
  if (phase === "cancelled" || phase === "idle") return "chip chip-muted";
  return "chip chip-warn";
}

export interface UploadTrayProps {
  queue: QueueState;
  /** Bytes per second over the recent window (0 = unknown). */
  throughput: number;
  formatBytes: (n: number) => string;
  onClear: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancelItem: (id: string) => void;
  onRetryItem: (id: string) => void;
  /** Change how many files upload at once. */
  onSetConcurrency: (n: number) => void;
}

/** The floating import tray. It owns its own UI state (collapsed, filter, open
 * detail) and is memoised, so a progress tick re-renders the tray only, not the
 * whole files page. */
export const UploadTray = memo(function UploadTray({
  queue,
  throughput,
  formatBytes,
  onClear,
  onPause,
  onResume,
  onCancelItem,
  onRetryItem,
  onSetConcurrency,
}: UploadTrayProps) {
  const [trayCollapsed, setTrayCollapsed] = useState(false);
  const [trayFilter, setTrayFilter] = useState<TrayFilter>("auto");
  const [detailId, setDetailId] = useState<string | null>(null);
  const transferActive = queue.active > 0;
  return (
  <section className="tray" aria-labelledby="tray-title">
    <div className="tray-head">
      <h2 id="tray-title">
        Import · {queue.done} sur {queue.items.length} terminé
        {queue.done > 1 ? "s" : ""}
      </h2>
      <button
        type="button"
        className="btn btn-ghost btn-small"
        aria-expanded={!trayCollapsed}
        onClick={() => setTrayCollapsed((value) => !value)}
      >
        {trayCollapsed ? "Agrandir" : "Réduire"}
      </button>
      {queue.finished ? (
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={onClear}
        >
          Effacer
        </button>
      ) : queue.schedulerPaused ? (
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={onResume}
        >
          Reprendre
        </button>
      ) : (
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={onPause}
        >
          Pause
        </button>
      )}
    </div>
    {/* Barre de progression globale */}
    {(() => {
      const totalBytes = queue.items.reduce((sum, item) => sum + item.sizeBytes, 0);
      const uploadedBytes = queue.items.reduce((sum, item) => sum + item.state.transferredBytes, 0);
      const pct = totalBytes > 0 ? Math.round((uploadedBytes / totalBytes) * 100) : 0;
      const remaining = totalBytes - uploadedBytes;
      const eta = throughput > 0 ? remaining / throughput : 0;
      // Progress restarts from zero at every retry, so a rate or an ETA computed
      // while files are being re-sent is meaningless: say so instead of showing it.
      const retrying = queue.items.some(
        (item) => item.state.attempts > 0 && ACTIVE_PHASES.includes(item.state.phase),
      );
      const formatEta = (s: number) => {
        if (!Number.isFinite(s) || s <= 0) return "";
        if (s < 60) return `~${Math.ceil(s)} s`;
        const totalMin = Math.ceil(s / 60);
        if (totalMin < 60) return `~${totalMin} min`;
        const h = Math.floor(totalMin / 60);
        return `~${h} h ${String(totalMin % 60).padStart(2, "0")} min`;
      };
      return totalBytes > 0 ? (
        <div className="tray-progress">
          <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <span className="progress-bar" style={{ width: `${pct}%` }} />
          </div>
          <span className="tray-progress-label">
            {formatBytes(uploadedBytes)} / {formatBytes(totalBytes)} ({pct}%)
            {retrying && !queue.finished ? (
              " · estimation indisponible (reprises en cours)"
            ) : throughput > 0 && !queue.finished ? (
              <>
                {" · "}
                {formatBytes(Math.round(throughput))}/s
                {eta > 0 ? ` · ${formatEta(eta)}` : ""}
              </>
            ) : null}
          </span>
        </div>
      ) : null;
    })()}
  <div
    className="transfer"
    data-testid="transfer-status"
    hidden={trayCollapsed}
  >
    {/* One short announcement per finished file; the per-byte texts of the
        list below are not live (a screen reader would read them nonstop). */}
    <span className="visually-hidden" role="status">
      {queue.done}/{queue.items.length} fichiers transférés
    </span>
    <div className="queue-head">
      <span className="muted">
        {queue.done}/{queue.items.length} transféré
        {queue.items.length > 1 ? "s" : ""}
        {queue.failed > 0 ? ` · ${queue.failed} en échec` : ""}
        {queue.cancelled > 0
          ? ` · ${queue.cancelled} annulé${queue.cancelled > 1 ? "s" : ""}`
          : ""}
      </span>
      {!queue.finished ? (
        <label className="muted queue-concurrency">
          Envois simultanés{" "}
          <select
            value={queue.maxConcurrency}
            onChange={(event) => onSetConcurrency(Number(event.target.value))}
            aria-describedby="queue-concurrency-hint"
          >
            {Array.from(new Set([...CONCURRENCY_CHOICES, queue.maxConcurrency]))
              .sort((a, b) => a - b)
              .map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
          </select>
          {transferActive && queue.concurrency < queue.maxConcurrency
            ? ` (${queue.concurrency} actuellement)`
            : ""}
        </label>
      ) : null}
    </div>
    {!queue.finished &&
    queue.maxConcurrency > 1 &&
    queue.items.some((item) => item.sizeBytes >= LARGE_FILE_BYTES && !item.state.checksum) ? (
      <p className="muted queue-detail" id="queue-concurrency-hint">
        Fichiers volumineux : plusieurs envois en parallèle se partagent votre connexion et
        chaque fichier dure plus longtemps. Si des fichiers sont interrompus et repris, choisissez
        1 envoi à la fois.
      </p>
    ) : null}
    {(() => {
      const count = (...phases: TransferPhase[]) =>
        queue.items.filter((item) => phases.includes(item.state.phase)).length;
      const parts = [
        [count("requesting-intent", "uploading"), "en envoi"],
        [count("validating"), "en vérification d'intégrité"],
        [count("idle"), "en attente"],
        [count("failed"), "en échec"],
        [count("available"), "disponibles"],
      ]
        .filter(([n]) => (n as number) > 0)
        .map(([n, label]) => `${n} ${label}`);
      return parts.length > 0 ? (
        <p className="muted queue-breakdown" data-testid="queue-breakdown">
          {parts.join(" · ")}
        </p>
      ) : null;
    })()}
    {queue.schedulerPaused ? (
      <p className="muted" role="status">
        Connexion perdue : la file est suspendue et reprendra
        automatiquement dès que le réseau revient.
      </p>
    ) : null}
    {transferActive &&
    queue.maxConcurrency > 1 &&
    queue.concurrency < queue.maxConcurrency ? (
      <p className="muted" role="status">
        Connexion difficile : envois limités à {queue.concurrency} à la
        fois — retour à {queue.maxConcurrency} dès que ça passe.
      </p>
    ) : null}
    {queue.items.length > TRAY_AUTO_ALL_MAX ? (
      <div className="queue-filter" role="group" aria-label="Fichiers affichés">
        {(
          [
            ["auto", "Auto"],
            ["active", "En cours"],
            ["failed", "Échecs"],
            ["all", "Tous"],
          ] as Array<[TrayFilter, string]>
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            className="btn btn-ghost btn-small"
            aria-pressed={trayFilter === value}
            onClick={() => setTrayFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
    ) : null}
    {(() => {
      if (trayCollapsed) return null;
      const mode =
        trayFilter === "auto"
          ? queue.items.length > TRAY_AUTO_ALL_MAX
            ? "active"
            : "all"
          : trayFilter;
      const needsAttention = (phase: TransferPhase) =>
        phase !== "available" && phase !== "idle" && phase !== "cancelled";
      const matching = queue.items.filter((item) =>
        mode === "all"
          ? true
          : mode === "failed"
            ? item.state.phase === "failed" || item.state.phase === "cancelled"
            : needsAttention(item.state.phase),
      );
      const shown = matching.slice(0, TRAY_ROW_CAP);
      // Position of each waiting file in the queue (1 = next to start).
      const waitingIndex = new Map<string, number>();
      let waitingSeen = 0;
      for (const item of queue.items) {
        if (item.state.phase === "idle") {
          waitingIndex.set(item.id, waitingSeen);
          waitingSeen += 1;
        }
      }
      const hiddenCount = queue.items.length - shown.length;
      return (
        <>
    <ul className="queue">
      {shown.map((item) => (
        <li key={item.id} className="queue-item">
          <div className="queue-line">
            <span className="transfer-name">{item.fileName}</span>
            <span className="muted">{formatBytes(item.sizeBytes)}</span>
            <span className={queuePhaseClass(item.state.phase)}>
              {PHASE_LABEL[item.state.phase]}
              {ACTIVE_PHASES.includes(item.state.phase) ? (
                <>
                  {" · "}
                  <Elapsed since={item.state.phaseSince} />
                </>
              ) : null}
            </span>
            {item.state.phase === "available" ? (
              <span className="chip chip-muted">SHA-256 vérifié</span>
            ) : null}
            <button
              type="button"
              className="btn btn-ghost btn-small"
              aria-expanded={detailId === item.id}
              aria-label={`Détails de ${item.fileName}`}
              onClick={() => setDetailId(detailId === item.id ? null : item.id)}
            >
              Détails
            </button>
            {ACTIVE_PHASES.includes(item.state.phase) ? (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                aria-label={`Interrompre ${item.fileName}`}
                onClick={() => onCancelItem(item.id)}
              >
                ×
              </button>
            ) : null}
            {item.state.phase === "failed" ||
            item.state.phase === "cancelled" ? (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                aria-label={`Relancer ${item.fileName}`}
                onClick={() => onRetryItem(item.id)}
              >
                Relancer
              </button>
            ) : null}
          </div>
          {item.state.phase === "uploading" ? (
            <div
              className="progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(item.state.progress * 100)}
              aria-label={`Progression de ${item.fileName}`}
            >
              <span
                className="progress-bar"
                style={{ width: `${Math.round(item.state.progress * 100)}%` }}
              />
            </div>
          ) : null}
          {item.state.phase === "uploading" ? (
            <p className="muted">
              {formatBytes(item.state.transferredBytes)} /{" "}
              {formatBytes(item.state.sizeBytes)} (
              {Math.round(item.state.progress * 100)} %)
            </p>
          ) : null}
          {detailId === item.id ? (
            <FileDetail item={item} formatBytes={formatBytes} />
          ) : null}
          {(() => {
            const text = describeItem(item, waitingIndex.get(item.id) ?? 0);
            return text ? <p className="muted queue-detail">{text}</p> : null;
          })()}
          {item.state.attempts > 0 &&
          ACTIVE_PHASES.includes(item.state.phase) ? (
            <p className="muted">
              Nouvelle tentative ({item.state.attempts})…
            </p>
          ) : null}
          {item.state.error && item.state.phase === "failed" ? (
            <p className="muted">{item.state.error}</p>
          ) : null}
        </li>
      ))}
    </ul>
    {hiddenCount > 0 ? (
      <p className="muted">
        {hiddenCount} autre{hiddenCount > 1 ? "s" : ""} fichier
        {hiddenCount > 1 ? "s" : ""} non affiché{hiddenCount > 1 ? "s" : ""} (
        {queue.done} transféré{queue.done > 1 ? "s" : ""}, {queue.failed} en échec) —
        choisissez « Tous » ou « Échecs » pour les parcourir.
      </p>
    ) : null}
        </>
      );
    })()}
  </div>
  </section>

  );
});
