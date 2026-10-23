import { Fragment } from "react";
import type { QueueItem } from "../../lib/transfer";
import { RowMenu } from "../RowMenu";
import type { RowMenuItem } from "../RowMenu";
import {
  CATEGORY_LABEL,
  addedAt,
  canCancelItem,
  canPauseItem,
  canResumeItem,
  canRetryItem,
  displayStatus,
  failureTitle,
  fileCategory,
  queuePositionLabel,
  STATUS_LABEL,
  STATUS_TONE,
} from "./model";
import type { DisplayStatus } from "./model";
import { TransferIcon } from "./TransferIcon";
import type { TransferIconName } from "./TransferIcon";
import { formatBytes, formatClock, formatRate } from "../../lib/format";

const CATEGORY_ICON: Record<string, TransferIconName> = {
  audio: "audio",
  video: "video",
  image: "image",
  pdf: "pdf",
  archive: "archive",
  other: "file",
};

function progressPercent(item: QueueItem): number {
  const status = displayStatus(item);
  if (status === "queued" || status === "paused") return 0;
  if (status === "completed") return 100;
  return Math.min(100, Math.round(item.state.progress * 100));
}

/**
 * The operational table. Desktop keeps a real table; below 768px each row is
 * laid out as a card by CSS (labels come from `data-label`), never a squeezed
 * table with horizontal scrolling.
 */
export function TransferList({
  items,
  visibleCount,
  selected,
  itemRates,
  positions,
  onToggle,
  onToggleAll,
  onPause,
  onResume,
  onCancel,
  onRetry,
  onDetails,
  onCopyError,
  onShowMore,
}: {
  items: QueueItem[];
  visibleCount: number;
  selected: ReadonlySet<string>;
  itemRates: ReadonlyMap<string, number>;
  positions: ReadonlyMap<string, number>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onDetails: (id: string) => void;
  onCopyError: (item: QueueItem) => void;
  onShowMore: () => void;
}) {
  const shown = items.slice(0, visibleCount);
  const hidden = items.length - shown.length;
  const allSelected = items.length > 0 && items.every((item) => selected.has(item.id));
  const someSelected =
    !allSelected && items.some((item) => selected.has(item.id));

  return (
    <section className="transfers-list" aria-label="Liste des transferts" data-testid="transfer-list">
      <table className="transfers-table">
        <caption className="visually-hidden">Liste des transferts de la session</caption>
        <thead>
          <tr>
            <th scope="col" className="transfers-col-select">
              <input
                type="checkbox"
                aria-label="Sélectionner tous les transferts filtrés"
                checked={allSelected}
                ref={(element) => {
                  if (element) element.indeterminate = someSelected;
                }}
                onChange={onToggleAll}
              />
            </th>
            <th scope="col">Nom du fichier</th>
            <th scope="col">Taille</th>
            <th scope="col">Progression</th>
            <th scope="col">Statut</th>
            <th scope="col" className="transfers-col-speed">Vitesse</th>
            <th scope="col" className="transfers-col-actions">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((item) => (
            <TransferRow
              key={item.id}
              item={item}
              selected={selected.has(item.id)}
              rate={itemRates.get(item.id) ?? 0}
              position={positions.get(item.id)}
              onToggle={onToggle}
              onPause={onPause}
              onResume={onResume}
              onCancel={onCancel}
              onRetry={onRetry}
              onDetails={onDetails}
              onCopyError={onCopyError}
            />
          ))}
        </tbody>
      </table>
      {hidden > 0 ? (
        <div className="transfers-more">
          <button type="button" className="btn" onClick={onShowMore}>
            Afficher {Math.min(50, hidden)} fichier{Math.min(50, hidden) > 1 ? "s" : ""} de plus
          </button>
          <span className="muted">
            {shown.length} sur {items.length} affichés
          </span>
        </div>
      ) : null}
    </section>
  );
}

function TransferRow({
  item,
  selected,
  rate,
  position,
  onToggle,
  onPause,
  onResume,
  onCancel,
  onRetry,
  onDetails,
  onCopyError,
}: {
  item: QueueItem;
  selected: boolean;
  rate: number;
  position: number | undefined;
  onToggle: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onDetails: (id: string) => void;
  onCopyError: (item: QueueItem) => void;
}) {
  const status: DisplayStatus = displayStatus(item);
  const tone = STATUS_TONE[status];
  const percent = progressPercent(item);
  const verifying = status === "verifying";
  const category = fileCategory(item.fileName);

  const actions: RowMenuItem[] = [];
  if (canPauseItem(item)) {
    actions.push({ label: "Mettre en pause", onSelect: () => onPause(item.id) });
  }
  if (canResumeItem(item)) {
    actions.push({ label: "Reprendre", onSelect: () => onResume(item.id) });
  }
  if (canCancelItem(item)) {
    actions.push({
      label: "Annuler",
      danger: true,
      onSelect: () => onCancel(item.id),
    });
  }
  if (canRetryItem(item)) {
    actions.push({ label: "Réessayer", onSelect: () => onRetry(item.id) });
  }
  actions.push({ label: "Détails", onSelect: () => onDetails(item.id) });

  return (
    <Fragment>
      <tr
        className={selected ? "transfers-row is-selected" : "transfers-row"}
        data-testid="transfer-row"
        data-status={status}
      >
        <td className="transfers-col-select" data-label="Sélection">
          <input
            type="checkbox"
            checked={selected}
            aria-label={`Sélectionner ${item.fileName}`}
            onChange={() => onToggle(item.id)}
          />
        </td>
        <td className="transfers-file" data-label="Fichier">
          <span
            className={`transfers-file-icon transfers-file-icon--${tone}`}
            aria-hidden="true"
          >
            <TransferIcon name={CATEGORY_ICON[category] ?? "file"} size={18} />
          </span>
          <span className="transfers-file-copy">
            <span className="transfers-file-name" title={item.fileName}>
              {item.fileName}
            </span>
            <span className="transfers-file-meta">
              {CATEGORY_LABEL[category]}
              {item.state.verifyMode ? ` · vérification ${item.state.verifyMode === "background" ? "en tâche de fond" : "en ligne"}` : ""}
              {addedAt(item) !== null
                ? ` · Ajouté à ${formatClock(addedAt(item) as number)}`
                : ""}
              {status === "queued" && position !== undefined
                ? ` · ${queuePositionLabel(position)}`
                : ""}
            </span>
          </span>
        </td>
        <td className="transfers-size" data-label="Taille">
          {formatBytes(item.sizeBytes)}
        </td>
        <td className="transfers-progress-cell" data-label="Progression">
          <div className="transfers-progress-head">
            <span className="transfers-progress-percent">
              {verifying ? "Vérification" : `${percent} %`}
            </span>
          </div>
          <div
            className={`transfers-bar transfers-bar--${tone}${verifying ? " is-indeterminate" : ""}`}
            role="progressbar"
            aria-label={`Progression de ${item.fileName}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={verifying ? undefined : percent}
            aria-valuetext={verifying ? "Vérification d'intégrité en cours" : `${percent} %`}
          >
            <span
              className="transfers-bar-fill"
              style={verifying ? undefined : { width: `${percent}%` }}
            />
          </div>
          <span className="transfers-progress-bytes">
            {formatBytes(item.state.transferredBytes)} / {formatBytes(item.sizeBytes)}
          </span>
        </td>
        <td className="transfers-status-cell" data-label="Statut">
          <span className={`transfer-badge transfer-badge--${tone}`}>
            <span className="transfer-badge-dot" aria-hidden="true" />
            {STATUS_LABEL[status]}
          </span>
        </td>
        <td className="transfers-speed transfers-col-speed" data-label="Vitesse">
          {status === "uploading" && rate > 0 ? formatRate(rate) : "—"}
        </td>
        <td className="transfers-col-actions" data-label="Actions">
          <RowMenu label={`Actions pour ${item.fileName}`} items={actions} />
        </td>
      </tr>
      {status === "failed" ? (
        <tr className="transfers-error-row">
          <td colSpan={7}>
            <div className="transfers-error-panel" data-testid="transfer-error-panel">
              <span className="transfers-error-icon" aria-hidden="true">
                <TransferIcon name="alert" size={20} />
              </span>
              <div className="transfers-error-copy">
                <p className="transfers-error-title">{failureTitle(item)}</p>
                <p className="transfers-error-text">
                  {item.state.error ??
                    "Le fichier n'a pas été publié. Vous pouvez demander une nouvelle tentative."}
                </p>
                {item.state.failureKind === "fatal" ? (
                  <p className="transfers-error-note">
                    Réessayer sans corriger la cause produira le même refus.
                  </p>
                ) : null}
              </div>
              <div className="transfers-error-actions">
                <button
                  type="button"
                  className="btn btn-small btn-primary"
                  onClick={() => onRetry(item.id)}
                >
                  <TransferIcon name="retry" size={15} />
                  Nouvelle tentative
                </button>
                <button
                  type="button"
                  className="btn btn-small"
                  onClick={() => onDetails(item.id)}
                >
                  <TransferIcon name="eye" size={15} />
                  Voir l'erreur
                </button>
                {item.state.error ? (
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={() => onCopyError(item)}
                  >
                    Copier l'erreur
                  </button>
                ) : null}
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}
