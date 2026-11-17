import { RowMenu } from "../RowMenu";
import { TransferIcon } from "./TransferIcon";

/**
 * One contextual action bar. The only permanent action is "Ajouter des fichiers";
 * session-wide controls appear only when they can actually do something, so a
 * disabled button never needs an explanation and actions are not repeated here,
 * in the bulk bar and in the row menu at the same time.
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
  exportCount,
  onExport,
  onDownloadSessionDiagnostic,
  onExportReport,
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
  exportCount: number;
  onExport: () => void;
  onDownloadSessionDiagnostic: () => void;
  onExportReport: () => void;
  onPauseAll: () => void;
  onResumeAll: () => void;
  onCancelAll: () => void;
  onAddFiles: () => void;
  onClear: () => void;
  onResetFilters: () => void;
  onRetryFailed: () => void;
}) {
  return (
    <div className="transfers-actionbar">
      <div className="transfers-actionbar-actions">
        <button
          type="button"
          className="btn btn-primary transfers-actionbar-primary"
          onClick={onAddFiles}
          aria-label="Ajouter des fichiers"
        >
          <TransferIcon name="plus" size={16} />
          Ajouter des fichiers
        </button>

        {canPause ? (
          <button type="button" className="btn" onClick={onPauseAll}>
            <TransferIcon name="pause" size={16} />
            Pause tous les transferts
          </button>
        ) : null}
        {canResume ? (
          <button type="button" className="btn" onClick={onResumeAll}>
            <TransferIcon name="play" size={16} />
            Reprendre
          </button>
        ) : null}
        {canCancel ? (
          <button type="button" className="btn btn-danger" onClick={onCancelAll}>
            <TransferIcon name="close" size={16} />
            Annuler tout
          </button>
        ) : null}

        <span className="transfers-menu-wrap" title="Plus d'actions sur les transferts">
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
                label: `Exporter la vue (${exportCount})`,
                onSelect: onExport,
                disabled: exportCount === 0,
              },
              {
                label: "Exporter le rapport complet",
                onSelect: onExportReport,
                disabled: exportCount === 0,
              },
              {
                label: "Télécharger le diagnostic de session",
                onSelect: onDownloadSessionDiagnostic,
                disabled: exportCount === 0,
              },
              {
                label: "Effacer la file terminée",
                onSelect: onClear,
                disabled: !canClear,
              },
              { label: "Réinitialiser les filtres", onSelect: onResetFilters },
            ]}
          />
        </span>
      </div>

      {activeCount > 0 && canPause ? (
        <p className="transfers-actionbar-hint">
          La pause suspend les fichiers qui n'ont pas encore démarré ; un envoi déjà
          commencé n'est pas interrompu.
        </p>
      ) : null}
    </div>
  );
}
