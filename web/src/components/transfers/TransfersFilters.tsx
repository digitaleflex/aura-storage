import type { TransferCounts, StatusFilter, SortKey } from "./model";
import { SORT_LABEL } from "./model";
import { TransferIcon } from "./TransferIcon";

export interface TransferFiltersProps {
  counts: TransferCounts;
  status: StatusFilter;
  onStatus: (status: StatusFilter) => void;
  search: string;
  onSearch: (value: string) => void;
  advancedOpen: boolean;
  onToggleAdvanced: () => void;
  typeFilter: string;
  onTypeFilter: (value: string) => void;
  minSize: string;
  onMinSize: (value: string) => void;
  maxSize: string;
  onMaxSize: (value: string) => void;
  sort: SortKey;
  onSort: (value: SortKey) => void;
  onReset: () => void;
}

/**
 * Client-side filters over the live queue (no network call per keystroke).
 * Counter values use the exact same predicates as the list, so the sum of the
 * exclusive tabs always matches "Tous".
 */
export function TransfersFilters({
  counts,
  status,
  onStatus,
  search,
  onSearch,
  advancedOpen,
  onToggleAdvanced,
  typeFilter,
  onTypeFilter,
  minSize,
  onMinSize,
  maxSize,
  onMaxSize,
  sort,
  onSort,
  onReset,
}: TransferFiltersProps) {
  const tabs: Array<{ key: StatusFilter; label: string; count: number }> = [
    { key: "all", label: "Tous", count: counts.total },
    { key: "active", label: "En cours", count: counts.active },
    { key: "queued", label: "En attente", count: counts.queued },
    ...(counts.paused > 0
      ? [{ key: "paused" as StatusFilter, label: "En pause", count: counts.paused }]
      : []),
    { key: "completed", label: "Terminés", count: counts.completed },
    { key: "failed", label: "Échecs", count: counts.failed },
    ...(counts.cancelled > 0
      ? [
          {
            key: "cancelled" as StatusFilter,
            label: "Annulés",
            count: counts.cancelled,
          },
        ]
      : []),
  ];

  return (
    <section className="transfers-filters" aria-label="Filtres des transferts" data-testid="transfer-filters">
      <div className="transfers-filters-row">
        <div className="transfers-tabs" role="group" aria-label="Statut des transferts">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={
                status === tab.key ? "transfers-tab is-active" : "transfers-tab"
              }
              aria-pressed={status === tab.key}
              onClick={() => onStatus(tab.key)}
            >
              {tab.label}
              <span className="transfers-tab-count">{tab.count}</span>
            </button>
          ))}
        </div>

        <div className="transfers-filters-right">
          <div className="transfers-search">
            <span className="transfers-search-icon" aria-hidden="true">
              <TransferIcon name="search" size={16} />
            </span>
            <label className="visually-hidden" htmlFor="transfers-search-input">
              Rechercher un fichier
            </label>
            <input
              id="transfers-search-input"
              type="search"
              value={search}
              placeholder="Rechercher un fichier…"
              onChange={(event) => onSearch(event.target.value)}
            />
            {search.length > 0 ? (
              <button
                type="button"
                className="transfers-search-clear"
                aria-label="Effacer la recherche"
                onClick={() => onSearch("")}
              >
                <TransferIcon name="close" size={14} />
              </button>
            ) : null}
          </div>
          <button
            type="button"
            className={
              advancedOpen
                ? "btn btn-small transfers-advanced-toggle is-open"
                : "btn btn-small transfers-advanced-toggle"
            }
            aria-expanded={advancedOpen}
            aria-controls="transfers-advanced-filters"
            onClick={onToggleAdvanced}
          >
            <TransferIcon name="sliders" size={16} />
            Filtres
          </button>
        </div>
      </div>

      {advancedOpen ? (
        <div
          className="transfers-advanced"
          id="transfers-advanced-filters"
          aria-label="Filtres avancés"
        >
          <label className="field transfers-field">
            <span>Type de fichier</span>
            <select value={typeFilter} onChange={(event) => onTypeFilter(event.target.value)}>
              <option value="all">Tous les types</option>
              <option value="audio">Audio</option>
              <option value="video">Vidéo</option>
              <option value="image">Image</option>
              <option value="pdf">PDF</option>
              <option value="archive">Archive</option>
              <option value="other">Autre</option>
            </select>
          </label>
          <label className="field transfers-field">
            <span>Taille min. (Mo)</span>
            <input
              type="number"
              min={0}
              step="0.1"
              value={minSize}
              onChange={(event) => onMinSize(event.target.value)}
            />
          </label>
          <label className="field transfers-field">
            <span>Taille max. (Mo)</span>
            <input
              type="number"
              min={0}
              step="0.1"
              value={maxSize}
              onChange={(event) => onMaxSize(event.target.value)}
            />
          </label>
          <label className="field transfers-field">
            <span>Ordre de tri</span>
            <select
              value={sort}
              onChange={(event) => onSort(event.target.value as SortKey)}
            >
              {(Object.keys(SORT_LABEL) as SortKey[]).map((key) => (
                <option key={key} value={key}>
                  {SORT_LABEL[key]}
                </option>
              ))}
            </select>
          </label>
          <div className="transfers-advanced-actions">
            <button type="button" className="btn btn-small" onClick={onReset}>
              Réinitialiser
            </button>
            <button
              type="button"
              className="btn btn-small btn-primary"
              onClick={onToggleAdvanced}
            >
              Appliquer
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
