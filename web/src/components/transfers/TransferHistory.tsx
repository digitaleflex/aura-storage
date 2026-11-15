import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { ApiError, api } from "../../lib/api";
import type {
  TransferHistoryQuery,
  TransferHistoryRecord,
  TransferHistoryStatus,
} from "../../lib/api";
import { formatBytes } from "../../lib/format";
import { TransferIcon } from "./TransferIcon";
import type { StatusTone } from "./model";

const HISTORY_PAGE_SIZE = 50;

type HistoryStatusFilter = TransferHistoryStatus | "all";

const STATUS_META: Record<
  TransferHistoryStatus,
  { label: string; tone: StatusTone }
> = {
  available: { label: "Disponible", tone: "success" },
  failed: { label: "Échec", tone: "danger" },
  aborted: { label: "Annulé", tone: "muted" },
  expired: { label: "Expiré", tone: "warning" },
};

const STATUS_TABS: Array<{
  key: HistoryStatusFilter;
  label: string;
}> = [
  { key: "all", label: "Tous" },
  { key: "available", label: "Disponibles" },
  { key: "failed", label: "En échec" },
  { key: "aborted", label: "Interrompus" },
  { key: "expired", label: "Expirés" },
];

const HISTORY_DATE_FORMAT = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "short",
  timeStyle: "short",
});

function formatHistoryDate(value: number | null | undefined): string {
  if (value === null || value === undefined || value <= 0) return "—";
  // Backend timestamps are epoch seconds, like the rest of the catalogue.
  const date = new Date(value > 1e12 ? value : value * 1000);
  if (Number.isNaN(date.getTime())) return "—";
  return HISTORY_DATE_FORMAT.format(date);
}

function formatHistorySize(record: TransferHistoryRecord): string {
  const size = record.final_size_bytes ?? record.expected_size_bytes;
  return size === null || size === undefined ? "—" : formatBytes(size);
}

function shortSessionId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

/**
 * Server-side transfer history (#246), deliberately distinct from the live
 * session queue above. The endpoint is read-only and may not be deployed yet:
 * a failed request is shown as "history unavailable", never as "no transfer".
 */
export function TransferHistory() {
  const [status, setStatus] = useState<HistoryStatusFilter>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const filters: TransferHistoryQuery = {
    status: status === "all" ? undefined : status,
    from: from || undefined,
    to: to || undefined,
  };

  const history = useInfiniteQuery({
    queryKey: ["transfer-history", filters.status, filters.from, filters.to],
    queryFn: ({ pageParam, signal }) =>
      api.listTransferHistory(
        { ...filters, limit: HISTORY_PAGE_SIZE, offset: pageParam },
        { signal },
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage, _pages, lastOffset) => {
      if (lastPage.next_offset !== undefined) {
        return lastPage.next_offset ?? undefined;
      }
      if (lastPage.has_more === false) return undefined;
      if (lastPage.total !== undefined) {
        const next = lastOffset + lastPage.items.length;
        return next < lastPage.total ? next : undefined;
      }
      if (lastPage.has_more === true) {
        return lastOffset + lastPage.items.length;
      }
      return lastPage.items.length === HISTORY_PAGE_SIZE
        ? lastOffset + lastPage.items.length
        : undefined;
    },
    retry: 1,
    staleTime: 30_000,
  });

  const records = history.data?.pages.flatMap((page) => page.items) ?? [];
  const errorStatus =
    history.error instanceof ApiError ? history.error.status : null;
  const notDeployed =
    errorStatus === 404 || errorStatus === 405 || errorStatus === 501;
  const hasFilters = status !== "all" || from !== "" || to !== "";

  function resetFilters() {
    setStatus("all");
    setFrom("");
    setTo("");
  }

  return (
    <section
      className="transfers-history"
      aria-labelledby="transfers-history-title"
      data-testid="transfer-history"
    >
      <div className="transfers-section-head">
        <div>
          <h2 id="transfers-history-title">Historique</h2>
          <p className="transfers-subtitle">
            Transferts terminés conservés par le serveur, toutes sessions
            confondues.
          </p>
        </div>
        <span className="transfers-session-chip">
          <TransferIcon name="clock" size={15} />
          Historique serveur
        </span>
      </div>

      {history.isError ? (
        <div className="transfers-history-note is-unavailable" role="status">
          <span className="transfers-history-note-icon" aria-hidden="true">
            <TransferIcon name="alert" size={20} />
          </span>
          <div className="transfers-history-note-copy">
            <strong>
              {notDeployed
                ? "Historique indisponible sur ce déploiement"
                : "Impossible de charger l'historique"}
            </strong>
            <p>
              Mode session uniquement : seuls les transferts de la session
              courante, ci-dessus, sont affichés. Aucun historique n&apos;est
              inventé.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => void history.refetch()}
          >
            Réessayer
          </button>
        </div>
      ) : (
        <>
          <section
            className="transfers-filters"
            aria-label="Filtres de l'historique"
          >
            <div className="transfers-filters-row">
              <div
                className="transfers-tabs"
                role="group"
                aria-label="Statut dans l'historique"
              >
                {STATUS_TABS.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    className={
                      status === tab.key
                        ? "transfers-tab is-active"
                        : "transfers-tab"
                    }
                    aria-pressed={status === tab.key}
                    onClick={() => setStatus(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="transfers-filters-right">
                <label className="field transfers-field transfers-history-date">
                  <span>Du</span>
                  <input
                    type="date"
                    value={from}
                    max={to || undefined}
                    onChange={(event) => setFrom(event.target.value)}
                  />
                </label>
                <label className="field transfers-field transfers-history-date">
                  <span>Au</span>
                  <input
                    type="date"
                    value={to}
                    min={from || undefined}
                    onChange={(event) => setTo(event.target.value)}
                  />
                </label>
                {hasFilters ? (
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={resetFilters}
                  >
                    Réinitialiser l&apos;historique
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn btn-small"
                  aria-label="Rafraîchir l'historique"
                  disabled={history.isFetching}
                  onClick={() => void history.refetch()}
                >
                  {history.isFetching ? "Actualisation…" : "Rafraîchir"}
                </button>
              </div>
            </div>
          </section>

          {history.isPending ? (
            <div className="transfers-history-note" role="status">
              <span className="transfers-history-note-icon" aria-hidden="true">
                <TransferIcon name="clock" size={20} />
              </span>
              <div className="transfers-history-note-copy">
                <strong>Chargement de l&apos;historique</strong>
                <p>Lecture des transferts terminés auprès du serveur…</p>
              </div>
            </div>
          ) : records.length === 0 ? (
            <section
              className="transfers-empty"
              aria-labelledby="transfers-history-empty-title"
            >
              <span className="transfers-empty-icon" aria-hidden="true">
                <TransferIcon name="clock" size={26} />
              </span>
              <h2 id="transfers-history-empty-title">
                Aucun transfert dans l&apos;historique
              </h2>
              <p>
                {hasFilters
                  ? "Aucun transfert terminé ne correspond à ces filtres."
                  : "Les transferts terminés apparaîtront ici après leur publication ou leur échec."}
              </p>
            </section>
          ) : (
            <section
              className="transfers-list"
              aria-label="Historique des transferts"
            >
              <table className="transfers-table">
                <caption className="visually-hidden">
                  Transferts terminés conservés par le serveur
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Fichier</th>
                    <th scope="col" className="transfers-col-size">
                      Taille
                    </th>
                    <th scope="col">Statut</th>
                    <th scope="col">Terminé le</th>
                    <th scope="col" className="transfers-col-session">
                      Session
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record) => {
                    const meta = STATUS_META[record.status];
                    const tone = meta?.tone ?? "muted";
                    const failure = record.error_message ?? record.failure_kind;
                    return (
                      <tr
                        key={record.id}
                        className="transfers-row"
                        data-status={record.status}
                        data-testid="transfer-history-row"
                      >
                        <td className="transfers-file" data-label="Fichier">
                          <span
                            className={`transfers-file-icon transfers-file-icon--${tone}`}
                            aria-hidden="true"
                          >
                            <TransferIcon name="file" size={18} />
                          </span>
                          <span className="transfers-file-copy">
                            <span
                              className="transfers-file-name"
                              title={record.display_name}
                            >
                              {record.display_name}
                            </span>
                            <span
                              className="transfers-file-meta"
                              title={failure ?? undefined}
                            >
                              {record.content_type ?? "Type inconnu"}
                              {record.failure_kind
                                ? ` · ${record.failure_kind}`
                                : ""}
                            </span>
                          </span>
                        </td>
                        <td
                          className="transfers-size transfers-col-size"
                          data-label="Taille"
                        >
                          {formatHistorySize(record)}
                        </td>
                        <td
                          className="transfers-status-cell"
                          data-label="Statut"
                        >
                          <span
                            className={`transfer-badge transfer-badge--${tone}`}
                            title={failure ?? undefined}
                          >
                            <span
                              className="transfer-badge-dot"
                              aria-hidden="true"
                            />
                            {meta?.label ?? record.status}
                          </span>
                        </td>
                        <td className="transfers-size" data-label="Terminé le">
                          {formatHistoryDate(
                            record.terminal_at ?? record.created_at,
                          )}
                        </td>
                        <td
                          className="transfers-size transfers-col-session"
                          data-label="Session"
                        >
                          <span
                            className="transfers-history-session"
                            title={record.transfer_session_id ?? undefined}
                          >
                            {shortSessionId(record.transfer_session_id)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {history.hasNextPage ? (
                <div className="transfers-more">
                  <button
                    type="button"
                    className="btn"
                    disabled={history.isFetchingNextPage}
                    onClick={() => void history.fetchNextPage()}
                  >
                    {history.isFetchingNextPage
                      ? "Chargement…"
                      : `Afficher ${HISTORY_PAGE_SIZE} transferts de plus`}
                  </button>
                  <span className="muted">
                    {records.length} transfert{records.length > 1 ? "s" : ""}{" "}
                    affiché{records.length > 1 ? "s" : ""}
                  </span>
                </div>
              ) : null}
            </section>
          )}
        </>
      )}
    </section>
  );
}
