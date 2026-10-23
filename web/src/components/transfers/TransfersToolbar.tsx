import { RowMenu } from "../RowMenu";
import { TransferIcon } from "./TransferIcon";

/**
 * Primary controls for the import session. Pause and cancel map to the
 * engine's own queue actions; nothing here fakes a server-side outcome.
 */
export function TransfersToolbar({
  canPause,
  canResume,
  canCancel,
  canClear,
  activeCount,
  failedCount,
  queuedCount,
  onSelectFailed,
  onSelectActive,
  onSelectQueued,
  onPauseAll,
  onResumeAll,
  onCancelAll,
  onAddFiles,
  onClear,
  onResetFilters,
  onRetryFailed,
}: {
  canPause: boolean;
  canResume: boolean;
  canCancel: boolean;
  canClear: boolean;
  activeCount: number;
  failedCount: number;
  queuedCount: number;
  onSelectFailed: () => void;
  onSelectActive: () => void;
  onSelectQueued: () => void;
  onPauseAll: () => void;
  onResumeAll: () => void;
  onCancelAll: () => void;
  onAddFiles: () => void;
  onClear: () => void;
  onResetFilters: () => void;
  onRetryFailed: () => void;
}) {
  return (
    <div className="transfers-toolbar">
      <div className="transfers-toolbar-actions">
        <button
          type="button"
          className="btn btn-primary transfers-toolbar-primary"
          onClick={onPauseAll}
          disabled={!canPause}
        >
          <TransferIcon name="pause" size={16} />
          Pause tous les transferts
        </button>
        <button
          type="button"
          className="btn"
          onClick={onResumeAll}
          disabled={!canResume}
        >
          <TransferIcon name="play" size={16} />
          Reprendre
        </button>
        <button type="button" className="btn" onClick={onAddFiles}>
          <TransferIcon name="plus" size={16} />
          Ajouter des fichiers
        </button>
        <button
          type="button"
          className="btn btn-danger transfers-toolbar-cancel"
          onClick={onCancelAll}
          disabled={!canCancel}
        >
          <TransferIcon name="close" size={16} />
          Annuler tout
        </button>
        <RowMenu
          label="Plus d'actions sur les transferts"
          items={[
            {
              label: `Relancer les échecs${failedCount > 0 ? ` (${failedCount})` : ""}`,
              onSelect: onRetryFailed,
              disabled: failedCount === 0,
            },
            {
              label: `Sélectionner les échecs (${failedCount})`,
              onSelect: onSelectFailed,
              disabled: failedCount === 0,
            },
            {
              label: `Sélectionner les actifs (${activeCount})`,
              onSelect: onSelectActive,
              disabled: activeCount === 0,
            },
            {
              label: `Sélectionner les fichiers en attente (${queuedCount})`,
              onSelect: onSelectQueued,
              disabled: queuedCount === 0,
            },
            {
              label: "Effacer la file terminée",
              onSelect: onClear,
              disabled: !canClear,
            },
            { label: "Réinitialiser les filtres", onSelect: onResetFilters },
          ]}
        />
      </div>
      {activeCount > 0 && canPause ? (
        <p className="transfers-toolbar-hint">
          La pause suspend les fichiers qui n'ont pas encore démarré ; un envoi
          déjà commencé n'est pas interrompu.
        </p>
      ) : null}
    </div>
  );
}
