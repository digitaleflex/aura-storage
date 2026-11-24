import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Loading } from "./Loading";

const percent = (rate: number) => `${Math.round(rate * 100)} %`;

/**
 * Portail public : ce qui s'écoute vraiment. Des comptages agrégés par livre,
 * sans visiteur identifiable. La carte reste discrète si l'API ne répond pas :
 * elle ne doit jamais gêner le reste de l'administration.
 */
export function PortalStats({ enabled }: { enabled: boolean }) {
  const stats = useQuery({
    queryKey: ["admin", "portal-stats"],
    queryFn: () => api.adminPortalStats(),
    enabled,
    retry: false,
  });
  if (stats.isError) return null;
  return (
    <section className="section" aria-labelledby="admin-portal-title" data-testid="portal-stats">
      <div className="section-head">
        <h2 id="admin-portal-title">Portail public</h2>
      </div>
      <p className="muted">
        Ce que les visiteurs écoutent. Comptages agrégés par livre : aucun visiteur n'est
        identifiable. Un livre est « terminé » quand un visiteur a atteint 90 % de sa durée.
      </p>
      {stats.isPending ? (
        <Loading label="Calcul des statistiques du portail" />
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat">
              <div className="value">{stats.data.totals.accounts}</div>
              <div className="label">Comptes visiteurs</div>
            </div>
            <div className="stat">
              <div className="value">{stats.data.totals.published_books}</div>
              <div className="label">Livres publiés</div>
            </div>
            <div className="stat">
              <div className="value">{stats.data.totals.listeners}</div>
              <div className="label">Écoutes commencées</div>
            </div>
            <div className="stat">
              <div className="value">{stats.data.totals.completed}</div>
              <div className="label">Livres terminés</div>
            </div>
            <div className="stat">
              <div className="value">{stats.data.totals.favorites}</div>
              <div className="label">Favoris</div>
            </div>
            <div className="stat">
              <div className="value">{stats.data.totals.views_month}</div>
              <div className="label">Ouvertures ({stats.data.period})</div>
            </div>
          </div>
          {stats.data.books.length === 0 ? (
            <p className="muted">Aucun livre publié pour le moment.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Livre</th>
                  <th>Auditeurs</th>
                  <th>Terminé</th>
                  <th>Favoris</th>
                  <th>Ouvertures du mois</th>
                </tr>
              </thead>
              <tbody>
                {stats.data.books.slice(0, 10).map((book) => (
                  <tr key={book.id}>
                    <td>
                      {book.title}
                      {book.author ? <span className="muted"> — {book.author}</span> : null}
                    </td>
                    <td>{book.listeners}</td>
                    <td>{book.listeners ? percent(book.completion_rate) : "—"}</td>
                    <td>{book.favorites}</td>
                    <td>{book.views_month}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
