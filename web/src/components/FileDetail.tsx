import { formatElapsed } from "./Elapsed";
import type { QueueItem, TransferPhase } from "../lib/transfer";

const LABEL: Record<TransferPhase, string> = {
  idle: "Mis en file",
  "requesting-intent": "Autorisation demandée",
  uploading: "Envoi des octets",
  validating: "Vérification d'intégrité",
  available: "Disponible",
  failed: "Échec",
  cancelled: "Annulé",
};

function clock(at: number): string {
  return new Date(at).toLocaleTimeString("fr-FR");
}

/** Everything the engine knows about one file: steps with their start time and
 * duration, size, object id, attempts, server SHA-256 and error. */
export function FileDetail({
  item,
  formatBytes,
}: {
  item: QueueItem;
  formatBytes: (n: number) => string;
}) {
  const st = item.state;
  const log = st.phaseLog ?? [];
  const terminal = st.phase === "available" || st.phase === "failed" || st.phase === "cancelled";
  const now = Date.now();
  return (
    <div className="file-detail" data-testid="file-detail">
      <dl className="file-detail-facts">
        <dt>Fichier</dt>
        <dd>{item.fileName}</dd>
        <dt>Taille</dt>
        <dd>{formatBytes(item.sizeBytes)}</dd>
        {st.intentId ? (
          <>
            <dt>Identifiant de l'objet</dt>
            <dd>
              <code>{st.intentId}</code>
            </dd>
          </>
        ) : null}
        <dt>Tentatives</dt>
        <dd>{st.attempts}</dd>
        {st.checksum ? (
          <>
            <dt>SHA-256 enregistré par le serveur</dt>
            <dd>
              <code className="file-detail-hash">{st.checksum}</code>
            </dd>
          </>
        ) : null}
        {st.error ? (
          <>
            <dt>Dernière erreur</dt>
            <dd>{st.error}</dd>
          </>
        ) : null}
      </dl>
      {log.length > 0 ? (
        <ol className="file-detail-steps" aria-label="Étapes">
          {log.map((entry, i) => {
            const next = log[i + 1];
            const end = next ? next.at : terminal ? entry.at : now;
            const isLast = i === log.length - 1;
            return (
              <li key={`${entry.phase}-${entry.at}`}>
                <span>{LABEL[entry.phase]}</span>{" "}
                <span className="muted">
                  à {clock(entry.at)}
                  {!isLast || !terminal ? ` · ${formatElapsed(end - entry.at)}` : ""}
                  {isLast && !terminal ? " (en cours)" : ""}
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="muted">Pas encore démarré.</p>
      )}
    </div>
  );
}
