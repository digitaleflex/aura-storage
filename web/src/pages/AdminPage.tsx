import { useQuery } from "@tanstack/react-query";
import { api, hasAdminAccess } from "../lib/api";
import type { IdentityItem } from "../lib/api";
import { useSession } from "../lib/auth";

const DATE_FMT = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatTs(ts: number | null | undefined): string {
  if (!ts) {
    return "—";
  }
  return DATE_FMT.format(new Date(ts * 1000));
}

/** Lifecycle label for a machine identity, derived from the API fields. */
function identityState(item: IdentityItem): { label: string; className: string } {
  if (item.revoked_at) {
    return { label: "Révoquée", className: "chip chip-muted" };
  }
  if (item.expires_at && item.expires_at * 1000 < Date.now()) {
    return { label: "Expirée", className: "chip chip-warn" };
  }
  return { label: "Active", className: "chip chip-ok" };
}

/** Read-only administration console (`admin:read`). No mutations here. */
export function AdminPage() {
  const session = useSession();
  const canAdmin = hasAdminAccess(session.data?.role);

  const stats = useQuery({
    queryKey: ["admin", "stats"],
    queryFn: () => api.adminStats(),
    enabled: canAdmin,
    retry: false,
  });
  const applications = useQuery({
    queryKey: ["admin", "applications"],
    queryFn: () => api.listApplications(),
    enabled: canAdmin,
    retry: false,
  });
  const spaces = useQuery({
    queryKey: ["admin", "spaces"],
    queryFn: () => api.listSpaces(),
    enabled: canAdmin,
    retry: false,
  });
  const identities = useQuery({
    queryKey: ["admin", "identities"],
    queryFn: () => api.listIdentities(),
    enabled: canAdmin,
    retry: false,
  });

  // The backend is the authority; this only keeps the UI honest.
  if (!canAdmin) {
    return (
      <div className="stack">
        <h1>Administration</h1>
        <p role="alert" className="alert alert-error">
          Accès refusé. Cette console est réservée aux rôles opérateur et
          administrateur.
        </p>
      </div>
    );
  }

  const appNames = new Map(
    (applications.data?.items ?? []).map((a) => [a.id, a.name]),
  );
  const spaceNames = new Map(
    (spaces.data?.items ?? []).map((s) => [s.id, s.name]),
  );

  const objectsByStatus = stats.data?.objects_by_status ?? {};
  const objectsTotal = Object.values(objectsByStatus).reduce((a, b) => a + b, 0);

  return (
    <div className="stack">
      <h1>Administration</h1>
      <p className="muted">
        Espaces, applications et identités machine-à-machine. Lecture seule :
        les opérations de création, rotation et révocation arrivent ensuite.
      </p>

      <section className="section" aria-labelledby="admin-stats-title">
        <h2 id="admin-stats-title">Tableau de bord</h2>
        {stats.isError ? (
          <p role="alert" className="alert alert-error">
            Statistiques indisponibles.
          </p>
        ) : stats.isPending ? (
          <p className="muted">Chargement…</p>
        ) : (
          <>
            <div className="stat-grid">
              <div className="stat">
                <div className="value">{objectsTotal}</div>
                <div className="label">Objets</div>
              </div>
              <div className="stat">
                <div className="value">{stats.data?.applications ?? 0}</div>
                <div className="label">Applications</div>
              </div>
              <div className="stat">
                <div className="value">{stats.data?.spaces ?? 0}</div>
                <div className="label">Espaces</div>
              </div>
              <div className="stat">
                <div className="value">{stats.data?.buckets ?? 0}</div>
                <div className="label">Buckets</div>
              </div>
              <div className="stat">
                <div className="value">
                  {stats.data?.active_service_identities ?? 0}
                  <span className="muted">
                    {" "}
                    / {stats.data?.service_identities ?? 0}
                  </span>
                </div>
                <div className="label">Identités actives</div>
              </div>
            </div>
            {Object.keys(objectsByStatus).length > 0 ? (
              <p className="muted">
                Objets par état :{" "}
                {Object.entries(objectsByStatus).map(([status, count]) => (
                  <span key={status} className="chip chip-muted">
                    {status} : {count}
                  </span>
                ))}
              </p>
            ) : null}
          </>
        )}
      </section>

      <section className="section" aria-labelledby="admin-apps-title">
        <h2 id="admin-apps-title">Applications</h2>
        {applications.isError ? (
          <p role="alert" className="alert alert-error">
            Applications indisponibles.
          </p>
        ) : (applications.data?.items.length ?? 0) === 0 ? (
          <p className="empty">Aucune application.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Nom</th>
                  <th scope="col">Statut</th>
                  <th scope="col">ID</th>
                </tr>
              </thead>
              <tbody>
                {applications.data?.items.map((a) => (
                  <tr key={a.id}>
                    <td className="name">{a.name}</td>
                    <td>
                      <span
                        className={
                          a.status === "active" ? "chip chip-ok" : "chip chip-muted"
                        }
                      >
                        {a.status}
                      </span>
                    </td>
                    <td className="num muted">{a.id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="section" aria-labelledby="admin-spaces-title">
        <h2 id="admin-spaces-title">Espaces</h2>
        {spaces.isError ? (
          <p role="alert" className="alert alert-error">
            Espaces indisponibles.
          </p>
        ) : (spaces.data?.items.length ?? 0) === 0 ? (
          <p className="empty">Aucun espace.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Nom</th>
                  <th scope="col">Environnement</th>
                  <th scope="col">Application</th>
                </tr>
              </thead>
              <tbody>
                {spaces.data?.items.map((s) => (
                  <tr key={s.id}>
                    <td className="name">{s.name}</td>
                    <td className="muted">{s.environment}</td>
                    <td className="muted">
                      {appNames.get(s.application_id) ?? s.application_id}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="section" aria-labelledby="admin-identities-title">
        <h2 id="admin-identities-title">Identités machine-à-machine</h2>
        <p className="muted">
          Les jetons ne sont jamais affichés ici : AURA n'en conserve que
          l'empreinte SHA-256. Un jeton n'est visible qu'une seule fois, à sa
          création ou à sa rotation.
        </p>
        {identities.isError ? (
          <p role="alert" className="alert alert-error">
            Identités indisponibles.
          </p>
        ) : (identities.data?.items.length ?? 0) === 0 ? (
          <p className="empty">Aucune identité de service.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Nom</th>
                  <th scope="col">Espace</th>
                  <th scope="col">Portées</th>
                  <th scope="col">État</th>
                  <th scope="col">Expire</th>
                </tr>
              </thead>
              <tbody>
                {identities.data?.items.map((i) => {
                  const state = identityState(i);
                  return (
                    <tr key={i.id}>
                      <td className="name">{i.name}</td>
                      <td className="muted">
                        {spaceNames.get(i.space_id) ?? i.space_id}
                      </td>
                      <td className="muted">{i.scopes.join(", ") || "—"}</td>
                      <td>
                        <span className={state.className}>{state.label}</span>
                      </td>
                      <td className="num muted">{formatTs(i.expires_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
