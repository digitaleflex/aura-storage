import type { QueueItem, TransferPhase } from "../../lib/transfer";
import { Dialog } from "../Dialog";
import {
  canCancelItem,
  canRetryItem,
  displayStatus,
  failureKindLabel,
  fileCategory,
  CATEGORY_LABEL,
  STATUS_LABEL,
  STATUS_TONE,
  addedAt,
} from "./model";
import { TransferIcon } from "./TransferIcon";
import { formatBytes, formatClock, formatMilliseconds } from "../../lib/format";

const PHASE_LABEL: Record<TransferPhase, string> = {
  idle: "En attente",
  "requesting-intent": "Autorisation demandée",
  uploading: "Envoi",
  validating: "Vérification d'intégrité",
  available: "Disponible",
  failed: "Échec",
  cancelled: "Annulé",
};

/**
 * Technical detail of one transfer. Only fields the engine actually exposes are
 * shown: no invented correlation id, no internal paths, no tokens.
 */
export function TransferDetailsDialog({
  item,
  onClose,
  onRetry,
  onCancel,
  onCopyName,
  onCopyError,
  onDownloadDiagnostic,
  addedAtById,
}: {
  item: QueueItem | null;
  onClose: () => void;
  onRetry: (id: string) => void;
  onCancel: (id: string) => void;
  onCopyName: (item: QueueItem) => void;
  onCopyError: (item: QueueItem) => void;
  onDownloadDiagnostic: (item: QueueItem) => void;
  addedAtById: ReadonlyMap<string, number>;
}) {
  const status = item ? displayStatus(item) : "queued";
  const percent = item
    ? Math.min(100, Math.round(item.state.progress * 100))
    : 0;
  const added = item ? addedAtById.get(item.id) ?? addedAt(item) : null;

  return (
    <Dialog
      open={item !== null}
      title={item ? `Détails — ${item.fileName}` : "Détails du transfert"}
      onClose={onClose}
    >
      {item ? (
        <div className="transfer-details" data-testid="transfer-details">
          <p className="dialog-text">
            Fiche technique du transfert : état, progression, empreinte SHA-256
            et journal des étapes.
          </p>
          <div className="transfer-details-head">
            <span className={`transfer-badge transfer-badge--${STATUS_TONE[status]}`}>
              {status === "verifying" ? (
                <TransferIcon name="shield" size={12} />
              ) : (
                <span className="transfer-badge-dot" aria-hidden="true" />
              )}
              {STATUS_LABEL[status]}
            </span>
            <span className="muted">
              {CATEGORY_LABEL[fileCategory(item.fileName)]} ·{" "}
              {formatBytes(item.sizeBytes)}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-small transfer-details-copy"
              onClick={() => onCopyName(item)}
            >
              Copier le nom
            </button>
          </div>

          <dl className="transfer-details-grid">
            <div>
              <dt>Transféré</dt>
              <dd>
                {formatBytes(item.state.transferredBytes)} /{" "}
                {formatBytes(item.sizeBytes)}
              </dd>
            </div>
            <div>
              <dt>Progression</dt>
              <dd>{percent} %</dd>
            </div>
            <div>
              <dt>Ajouté</dt>
              <dd>{added !== null ? formatClock(added) : "—"}</dd>
            </div>
            <div>
              <dt>Dernier changement d'étape</dt>
              <dd>
                {item.state.phaseSince !== undefined
                  ? formatClock(item.state.phaseSince)
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>Tentatives</dt>
              <dd>{item.state.attempts}</dd>
            </div>
            <div>
              <dt>Vérification</dt>
              <dd>
                {item.state.verifyMode === "background"
                  ? "En tâche de fond"
                  : item.state.verifyMode === "inline"
                    ? "En ligne (avant publication)"
                    : "Non communiquée"}
              </dd>
            </div>
            <div>
              <dt>Empreinte SHA-256</dt>
              <dd className="mono transfer-details-checksum">
                {item.state.checksum || "—"}
              </dd>
            </div>
            <div>
              <dt>Commit serveur</dt>
              <dd>
                {item.state.commitTiming
                  ? `${formatMilliseconds(item.state.commitTiming.total_ms)} (métadonnées ${formatMilliseconds(
                      item.state.commitTiming.head_ms,
                    )} · SHA-256 ${formatMilliseconds(item.state.commitTiming.hash_ms)})`
                  : "—"}
              </dd>
            </div>
          </dl>

          {item.state.phase === "failed" ? (
            <div className="transfer-details-error">
              <p className="transfer-details-error-title">
                {failureKindLabel(item)}
              </p>
              <p>{item.state.error ?? "Aucun message fourni par le serveur."}</p>
              <p className="muted">
                Les traces internes et les chemins serveur ne sont jamais exposés
                ici.
              </p>
            </div>
          ) : null}

          <div className="transfer-details-timeline">
            <h3>Étapes</h3>
            <ol>
              {item.state.phaseLog?.map((entry, index) => (
                <li key={`${entry.phase}-${entry.at}-${index}`}>
                  <span>{PHASE_LABEL[entry.phase]}</span>
                  <span className="mono">{formatClock(entry.at)}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="transfer-details-actions">
            {canRetryItem(item) ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => onRetry(item.id)}
              >
                <TransferIcon name="retry" size={15} />
                Nouvelle tentative
              </button>
            ) : null}
            {item.state.error ? (
              <button
                type="button"
                className="btn"
                onClick={() => onCopyError(item)}
              >
                Copier l'erreur
              </button>
            ) : null}
            {item.state.phase === "failed" ? (
              <button
                type="button"
                className="btn"
                onClick={() => onDownloadDiagnostic(item)}
              >
                Télécharger le diagnostic
              </button>
            ) : null}
            {canCancelItem(item) ? (
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => onCancel(item.id)}
              >
                Annuler ce transfert
              </button>
            ) : null}
            <button type="button" className="btn" onClick={onClose}>
              Fermer
            </button>
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}

/**
 * Confirmation for a destructive queue action. It states exactly what is
 * aborted, and that verified files already stored are kept.
 */
export interface CancelPreview {
  active: number;
  queued: number;
  completed: number;
}

function describeCancelPreview(preview: CancelPreview): string {
  const parts: string[] = [];
  if (preview.active > 0) {
    parts.push(
      `${preview.active} envoi${preview.active > 1 ? "s" : ""} en cours sera${
        preview.active > 1 ? "ont" : ""
      } interrompu${preview.active > 1 ? "s" : ""}.`,
    );
  }
  if (preview.queued > 0) {
    parts.push(
      `${preview.queued} fichier${preview.queued > 1 ? "s" : ""} en attente sera${
        preview.queued > 1 ? "ont" : ""
      } annulé${preview.queued > 1 ? "s" : ""}.`,
    );
  }
  if (parts.length === 0) return "Aucun transfert actif ne sera interrompu.";
  return parts.join(" ");
}

export function TransferCancelDialog({
  open,
  scope,
  preview,
  onClose,
  onConfirm,
}: {
  open: boolean;
  scope: "all" | "selection";
  preview: CancelPreview;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const count = preview.active + preview.queued;
  const plural = count > 1;
  return (
    <Dialog
      open={open}
      title={
        scope === "all"
          ? "Annuler tous les transferts ?"
          : `Annuler ${count} transfert${plural ? "s" : ""} sélectionné${plural ? "s" : ""} ?`
      }
      onClose={onClose}
    >
      <div data-testid="transfer-cancel-dialog">
        <p className="dialog-text">
          {scope === "all"
            ? "Cette annulation concerne la file de la session :"
            : `Cette annulation concerne ${count} transfert${plural ? "s" : ""} sélectionné${plural ? "s" : ""} :`}{" "}
          {describeCancelPreview(preview)}{" "}
          {preview.completed > 0
            ? `${preview.completed} fichier${preview.completed > 1 ? "s" : ""} déjà vérifié${preview.completed > 1 ? "s" : ""} ${preview.completed > 1 ? "restent" : "reste"} dans votre stockage.`
            : ""}
        </p>
        <p className="dialog-text">
          Les fichiers déjà vérifiés et disponibles restent dans votre stockage.
          Cette action ne peut pas être annulée pour cette session.
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Retour
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>
            {scope === "all" ? "Tout annuler" : "Annuler la sélection"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
