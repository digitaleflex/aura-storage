import { useState } from "react";
import { useAuth } from "../lib/auth";
import {
  DIAG_DOWNLOAD_BYTES,
  DIAG_UPLOAD_BYTES,
  clearHistory,
  formatRatePair,
  loadHistory,
  pushHistory,
  runDownload,
  runPing,
  runUpload,
  verdict,
} from "../lib/diag";
import type { DiagRecord, PingStats, RateSample, UploadSample } from "../lib/diag";
import { describeError } from "../lib/errors";

/**
 * Diagnostic réseau : mesure le chemin réel navigateur → Aura (TLS, Traefik,
 * API) et non le lien de l'opérateur vers un serveur tiers. Trois mesures :
 * RTT/gigue, descente en flux, montée comparée côté navigateur et côté serveur.
 */

type Phase = "idle" | "ping" | "download" | "upload" | "done" | "failed";

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Prêt",
  ping: "Mesure des allers-retours…",
  download: "Mesure de la descente…",
  upload: "Mesure de la montée…",
  done: "Terminé",
  failed: "Interrompu",
};

const RUNNING: Phase[] = ["ping", "download", "upload"];

function ms(value: number): string {
  return `${value.toFixed(0)} ms`;
}

export function DiagPage() {
  const { csrf } = useAuth();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [ping, setPing] = useState<PingStats | null>(null);
  const [down, setDown] = useState<RateSample | null>(null);
  const [up, setUp] = useState<UploadSample | null>(null);
  const [progress, setProgress] = useState(0);
  const [history, setHistory] = useState<DiagRecord[]>(() => loadHistory());

  const running = RUNNING.includes(phase);

  async function run(): Promise<void> {
    setError(null);
    setPing(null);
    setDown(null);
    setUp(null);
    setProgress(0);
    try {
      setPhase("ping");
      const pings = await runPing();
      setPing(pings);

      setPhase("download");
      const download = await runDownload(DIAG_DOWNLOAD_BYTES, (loaded, total) => {
        setProgress(total > 0 ? loaded / total : 0);
      });
      setDown(download);

      setPhase("upload");
      setProgress(0);
      const upload = await runUpload(DIAG_UPLOAD_BYTES, csrf);
      setUp(upload);
      setHistory(
        pushHistory({
          at: Date.now(),
          rttMin: pings.min,
          rttAvg: pings.avg,
          rttMax: pings.max,
          jitter: pings.jitter,
          downBytesPerSecond: download.bytesPerSecond,
          upBytesPerSecond: upload.bytesPerSecond,
          upServerBytesPerSecond: upload.serverBytesPerSecond,
        }),
      );
      setPhase("done");
    } catch (err) {
      setError(describeError(err, "Diagnostic interrompu. Réessayez dans un instant."));
      setPhase("failed");
    }
  }

  const lostPercent =
    up && up.bytesPerSecond > 0
      ? Math.round((up.serverBytesPerSecond / up.bytesPerSecond - 1) * 100)
      : null;

  return (
    <div className="stack diag-page" data-testid="diag-page">
      <div className="page-head">
        <h1>Diagnostic réseau</h1>
      </div>

      <section className="section" aria-labelledby="diag-run-title">
        <div className="section-head">
          <h2 id="diag-run-title">Test du chemin vers Aura</h2>
        </div>
        <p className="muted">
          Ces mesures passent par le même chemin que vos envois (TLS, proxy,
          API). Elles disent ce que votre poste obtient réellement d&apos;Aura,
          ce qu&apos;un test de débit classique ne peut pas dire : il mesure un
          autre serveur. Rien n&apos;est stocké ; 10 Mo sont lus et 5 Mo envoyés
          puis jetés.
        </p>

        <div className="diag-actions">
          <button type="button" className="btn" onClick={() => void run()} disabled={running}>
            {running ? "Test en cours…" : "Lancer le test (30 s)"}
          </button>
          {running ? (
            <progress
              aria-label="Progression du test"
              max={1}
              value={phase === "download" || phase === "upload" ? progress : 0}
            />
          ) : null}
        </div>

        <p role="status" aria-live="polite" className="muted">
          {PHASE_LABEL[phase]}
        </p>

        {error ? (
          <p role="alert" className="alert alert-error">
            {error}
            <button type="button" className="btn btn-ghost btn-small" onClick={() => void run()}>
              Réessayer
            </button>
          </p>
        ) : null}
      </section>

      {ping || down || up ? (
        <section className="section" aria-labelledby="diag-result-title">
          <div className="section-head">
            <h2 id="diag-result-title">Résultats</h2>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Mesure</th>
                <th>Valeur</th>
                <th>Lecture</th>
              </tr>
            </thead>
            <tbody>
              {ping ? (
                <>
                  <tr>
                    <td>Aller-retour (RTT)</td>
                    <td>{`${ms(ping.min)} / ${ms(ping.avg)} / ${ms(ping.max)}`}</td>
                    <td>minimum / moyen / maximum</td>
                  </tr>
                  <tr>
                    <td>Gigue</td>
                    <td>{ms(ping.jitter)}</td>
                    <td>
                      {ping.jitter > 80
                        ? "instable : les coupures viennent peut-être de là"
                        : "stable"}
                    </td>
                  </tr>
                </>
              ) : null}
              {down ? (
                <tr>
                  <td>Descente</td>
                  <td>{formatRatePair(down.bytesPerSecond)}</td>
                  <td>{`${(down.bytes / 1_000_000).toFixed(1).replace(".", ",")} Mo en ${(
                    down.durationMs / 1000
                  )
                    .toFixed(1)
                    .replace(".", ",")} s`}</td>
                </tr>
              ) : null}
              {up ? (
                <>
                  <tr>
                    <td>Montée (navigateur)</td>
                    <td>{formatRatePair(up.bytesPerSecond)}</td>
                    <td>
                      <span className={`chip chip-${verdict(up.bytesPerSecond).tone === "ok" ? "ok" : "warn"}`}>
                        {verdict(up.bytesPerSecond).label}
                      </span>
                    </td>
                  </tr>
                  <tr>
                    <td>Montée (serveur)</td>
                    <td>{formatRatePair(up.serverBytesPerSecond)}</td>
                    <td>
                      {lostPercent === null
                        ? "non mesurable"
                        : lostPercent <= -20
                          ? `${Math.abs(lostPercent)} % plus lent côté serveur : octets perdus ou bridés en route`
                          : "cohérent avec le navigateur"}
                    </td>
                  </tr>
                </>
              ) : null}
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="section" aria-labelledby="diag-history-title">
        <div className="section-head">
          <h2 id="diag-history-title">Historique (ce navigateur)</h2>
          {history.length > 0 ? (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => {
                clearHistory();
                setHistory([]);
              }}
            >
              Effacer l&apos;historique
            </button>
          ) : null}
        </div>
        <p className="muted">
          Les {history.length === 0 ? "20" : history.length} dernières mesures restent
          dans ce navigateur uniquement : rien n&apos;est envoyé ni conservé sur le
          serveur. Comparer 8 h et 20 h distingue une saturation aux heures pleines
          d&apos;un incident permanent.
        </p>
        {history.length === 0 ? (
          <p className="muted">Aucune mesure enregistrée pour l&apos;instant.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>RTT moy.</th>
                <th>Gigue</th>
                <th>Descente</th>
                <th>Montée</th>
              </tr>
            </thead>
            <tbody>
              {history.map((entry) => (
                <tr key={entry.at}>
                  <td>
                    {new Date(entry.at).toLocaleString("fr-FR", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td>{ms(entry.rttAvg)}</td>
                  <td>{ms(entry.jitter)}</td>
                  <td>{formatRatePair(entry.downBytesPerSecond)}</td>
                  <td>{formatRatePair(entry.upBytesPerSecond)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
