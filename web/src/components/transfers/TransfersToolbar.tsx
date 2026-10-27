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
  exportCount,
  onExport,
  onDownloadSessionDiagnostic,
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
          title={
            canPause ? undefined : "Aucun transfert en attente à suspendre."
          }
        >
          <TransferIcon name="pause" size={16} />
          Pause tous les transferts
        </button>
        <button
          type="button"
          className="btn"
          onClick={onResumeAll}
          disabled={!canResume}
          title={
            canResume
              ? undefined
              : "Aucun transfert en pause ou suspendu à reprendre."
          }
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
          title={
            canCancel
              ? undefined
              : "Aucun transfert en cours ou en attente à annuler."
          }
        >
          <TransferIcon name="close" size={16} />
          Annuler tout
        </button>
        <span
          className="transfers-menu-wrap"
          title="Plus d'actions sur les transferts"
        >
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
        <p className="transfers-toolbar-hint">
          La pause suspend les fichiers qui n'ont pas encore démarré ; un envoi
          déjà commencé n'est pas interrompu.
        </p>
      ) : null}
    </div>
  );
}
