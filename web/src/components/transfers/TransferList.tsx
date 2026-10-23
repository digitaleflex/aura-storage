import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
import type {
  DisplayStatus,
  SortDirection,
  SortKey,
} from "./model";
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

/** Above this many rows, only the rows near the viewport are in the DOM. */
const VIRTUALIZE_THRESHOLD = 200;
const INITIAL_WINDOW = 40;
const FALLBACK_ROW_HEIGHT = 64;
const FALLBACK_ERROR_HEIGHT = 124;
const OVERSCAN_PX = 3 * FALLBACK_ROW_HEIGHT;

interface RowOffset {
  start: number;
  height: number;
}

/** First row whose bottom edge is below `position` (binary search). */
function findRowAt(offsets: RowOffset[], position: number): number {
  let low = 0;
  let high = offsets.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    const row = offsets[middle]!;
    if (row.start + row.height <= position) low = middle + 1;
    else high = middle;
  }
  return low;
}

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
  addedAtById,
  highlights,
  sort,
  sortDirection,
  onSort,
  onToggle,
  onToggleAll,
  onPause,
  onResume,
  onCancel,
  onRetry,
  onDetails,
  onCopyError,
  onDownloadDiagnostic,
  onShowMore,
}: {
  items: QueueItem[];
  visibleCount: number;
  selected: ReadonlySet<string>;
  itemRates: ReadonlyMap<string, number>;
  positions: ReadonlyMap<string, number>;
  addedAtById: ReadonlyMap<string, number>;
  highlights: ReadonlyMap<string, "success" | "danger">;
  sort: SortKey;
  sortDirection: SortDirection;
  onSort: (key: SortKey) => void;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onDetails: (id: string) => void;
  onCopyError: (item: QueueItem) => void;
  onDownloadDiagnostic: (item: QueueItem) => void;
  onShowMore: () => void;
}) {
  const virtual = items.length > VIRTUALIZE_THRESHOLD;
  const [range, setRange] = useState({
    start: 0,
    end: Math.min(INITIAL_WINDOW, items.length),
  });
  const [measured, setMeasured] = useState({
    normal: FALLBACK_ROW_HEIGHT,
    error: FALLBACK_ERROR_HEIGHT,
  });
  const listRef = useRef<HTMLElement | null>(null);

  const offsets = useMemo<RowOffset[]>(() => {
    let cursor = 0;
    return items.map((item) => {
      const height =
        measured.normal +
        (displayStatus(item) === "failed" ? measured.error : 0);
      const row = { start: cursor, height };
      cursor += height;
      return row;
    });
  }, [items, measured]);
  const totalHeight =
    offsets.length > 0
      ? offsets[offsets.length - 1]!.start + offsets[offsets.length - 1]!.height
      : 0;

  const offsetsRef = useRef(offsets);
  offsetsRef.current = offsets;

  const computeRange = useCallback(() => {
    if (!virtual) return;
    const element = listRef.current;
    const rows = offsetsRef.current;
    if (!element || rows.length === 0) return;
    // The virtualized list scrolls inside its own container, not the page.
    const viewTop = element.scrollTop;
    const viewBottom = viewTop + element.clientHeight;
    const start = Math.max(0, findRowAt(rows, viewTop - OVERSCAN_PX));
    const end = Math.min(
      rows.length,
      findRowAt(rows, viewBottom + OVERSCAN_PX) + 1,
    );
    setRange((previous) =>
      previous.start === start && previous.end === end
        ? previous
        : { start, end },
    );
  }, [virtual]);

  useEffect(() => {
    if (!virtual) return;
    const element = listRef.current;
    if (!element) return;
    computeRange();
    let frame = 0;
    const onScrollOrResize = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        computeRange();
      });
    };
    element.addEventListener("scroll", onScrollOrResize, { passive: true });
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      element.removeEventListener("scroll", onScrollOrResize);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [virtual, computeRange]);

  // Rows can change (filter, completion, error panel): recompute the window.
  useEffect(() => {
    if (virtual) computeRange();
  }, [virtual, offsets, computeRange]);

  // Measure one normal and one error row so spacer arithmetic matches the
  // actual rendering (borders, padding and fonts included).
  useLayoutEffect(() => {
    if (!virtual) return;
    const element = listRef.current;
    if (!element) return;
    const normal = element.querySelector<HTMLElement>(
      '[data-testid="transfer-row"]:not([data-status="failed"])',
    ) ?? element.querySelector<HTMLElement>('[data-testid="transfer-row"]');
    const error = element.querySelector<HTMLElement>(".transfers-error-row");
    const normalHeight = normal?.getBoundingClientRect().height ?? 0;
    const errorHeight = error?.getBoundingClientRect().height ?? 0;
    setMeasured((previous) => {
      const nextNormal =
        normalHeight > 0 ? normalHeight : previous.normal;
      const nextError = errorHeight > 0 ? errorHeight : previous.error;
      if (
        Math.abs(nextNormal - previous.normal) < 0.5 &&
        Math.abs(nextError - previous.error) < 0.5
      ) {
        return previous;
      }
      return { normal: nextNormal, error: nextError };
    });
  }, [virtual, range, offsets]);

  const shown = virtual
    ? items.slice(range.start, range.end)
    : items.slice(0, visibleCount);
  const hidden = virtual ? 0 : items.length - shown.length;
  const topSpacer = virtual && offsets[range.start] ? offsets[range.start]!.start : 0;
  const bottomSpacer = virtual
    ? Math.max(
        0,
        totalHeight -
          (offsets[range.end - 1]
            ? offsets[range.end - 1]!.start + offsets[range.end - 1]!.height
            : 0),
      )
    : 0;
  const allSelected = items.length > 0 && items.every((item) => selected.has(item.id));
  const someSelected =
    !allSelected && items.some((item) => selected.has(item.id));

  return (
    <section
      ref={listRef}
      className={`transfers-list${virtual ? " transfers-list--virtual" : ""}`}
      aria-label="Liste des transferts"
      data-testid="transfer-list"
      data-virtualized={virtual ? "true" : "false"}
    >
      <table className="transfers-table" aria-rowcount={items.length}>
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
            <SortableHeader
              label="Nom du fichier"
              field="name"
              sort={sort}
              direction={sortDirection}
              onSort={onSort}
            />
            <SortableHeader
              label="Taille"
              field="size"
              sort={sort}
              direction={sortDirection}
              onSort={onSort}
              className="transfers-col-size"
            />
            <th scope="col">Progression</th>
            <SortableHeader
              label="Statut"
              field="status"
              sort={sort}
              direction={sortDirection}
              onSort={onSort}
            />
            <th scope="col" className="transfers-col-speed">Vitesse</th>
            <th scope="col" className="transfers-col-actions">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {topSpacer > 0 ? (
            <tr className="transfers-spacer" aria-hidden="true">
              <td colSpan={7} style={{ height: topSpacer }} />
            </tr>
          ) : null}
          {shown.map((item, index) => (
            <TransferRow
              key={item.id}
              rowIndex={virtual ? range.start + index + 1 : undefined}
              item={item}
              selected={selected.has(item.id)}
              rate={itemRates.get(item.id) ?? 0}
              position={positions.get(item.id)}
              addedAtMs={addedAtById.get(item.id) ?? addedAt(item)}
              highlight={highlights.get(item.id)}
              onToggle={onToggle}
              onPause={onPause}
              onResume={onResume}
              onCancel={onCancel}
              onRetry={onRetry}
              onDetails={onDetails}
              onCopyError={onCopyError}
              onDownloadDiagnostic={onDownloadDiagnostic}
            />
          ))}
          {bottomSpacer > 0 ? (
            <tr className="transfers-spacer" aria-hidden="true">
              <td colSpan={7} style={{ height: bottomSpacer }} />
            </tr>
          ) : null}
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
  rowIndex,
  selected,
  rate,
  position,
  addedAtMs,
  highlight,
  onToggle,
  onPause,
  onResume,
  onCancel,
  onRetry,
  onDetails,
  onCopyError,
  onDownloadDiagnostic,
}: {
  item: QueueItem;
  rowIndex?: number;
  selected: boolean;
  rate: number;
  position: number | undefined;
  addedAtMs: number | null;
  highlight: "success" | "danger" | undefined;
  onToggle: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onDetails: (id: string) => void;
  onCopyError: (item: QueueItem) => void;
  onDownloadDiagnostic: (item: QueueItem) => void;
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
        className={`transfers-row${selected ? " is-selected" : ""}${
          highlight === "success" ? " is-just-completed" : ""
        }${highlight === "danger" ? " is-just-failed" : ""}`}
        data-testid="transfer-row"
        data-status={status}
        aria-rowindex={rowIndex}
        data-highlight={highlight}
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
              {addedAtMs !== null
                ? ` · Ajouté à ${formatClock(addedAtMs)}`
                : ""}
              {status === "queued" && position !== undefined
                ? ` · ${queuePositionLabel(position)}`
                : ""}
            </span>
          </span>
        </td>
        <td className="transfers-size transfers-col-size" data-label="Taille">
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
                <button
                  type="button"
                  className="btn btn-small"
                  onClick={() => onDownloadDiagnostic(item)}
                >
                  Télécharger le diagnostic
                </button>
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}

/** A table header that toggles the sort order with a real button (keyboard). */
function SortableHeader({
  label,
  field,
  sort,
  direction,
  onSort,
  className,
}: {
  label: string;
  field: SortKey;
  sort: SortKey;
  direction: SortDirection;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = sort === field;
  return (
    <th
      scope="col"
      aria-sort={
        active ? (direction === "asc" ? "ascending" : "descending") : "none"
      }
      className={className}
    >
      <button
        type="button"
        className={`transfers-sort${active ? " is-active" : ""}`}
        onClick={() => onSort(field)}
      >
        {label}
        <span className="transfers-sort-arrow" aria-hidden="true">
          {active ? (direction === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </th>
  );
}
