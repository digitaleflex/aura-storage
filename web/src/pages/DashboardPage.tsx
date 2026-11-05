import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useAuth, useSession } from "../lib/auth";
import { api, type UsageResponse, type AdminStats } from "../lib/api";
import { describeError } from "../lib/errors";
import { VaultMark } from "../components/VaultMark";
import { ToastStack, makeToast, type Toast } from "../components/Toasts";

export function DashboardPage() {
  const { logout } = useAuth();
  const session = useSession();
  const navigate = useNavigate();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function notify(kind: Toast["kind"], text: string) {
    setToasts((current) => [...current.slice(-3), makeToast(kind, text)]);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const me = await api.me();
        setIsAdmin(me.role === "admin");

        if (me.role === "admin") {
          const [u, s] = await Promise.all([
            api.adminUsage(),
            api.adminStats(),
          ]);
          if (!cancelled) {
            setUsage(u);
            setStats(s);
          }
        }
        if (!cancelled) setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(describeError(err, "Erreur inconnue."));
          notify("error", "Impossible de charger le tableau de bord.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="dashboard-page" data-testid="dashboard-page">
        <VaultMark size={32} />
        <p>Chargement du tableau de bord&hellip;</p>
      </div>
    );
  }

  const userName = session.data?.name ?? "utilisateur";
  const totalObjects =
    stats && stats.objects_by_status
      ? Object.values(stats.objects_by_status).reduce((a, b) => a + b, 0)
      : 0;
  const storedBytes = usage?.totals?.stored_bytes ?? 0;
  const capacityBytes = usage?.capacity?.capacity_bytes;
  const usagePct =
    capacityBytes
      ? Math.round((storedBytes / capacityBytes) * 100)
      : null;

  return (
    <div className="dashboard-page" data-testid="dashboard-page">
      <ToastStack toasts={toasts} onDismiss={(id: number) =>
        setToasts((current) => current.filter((t) => t.id !== id))
      } />
      <div className="dashboard-shell">
        <VaultMark size={32} />
        <div className="dashboard-header">
          <h1>Tableau de bord</h1>
          <p className="dashboard-subtitle">
            Vue d&rsquo;espace de {userName}
          </p>
        </div>

        {error && (
          <div className="dashboard-error" role="alert">
            {error}
            <button
              type="button"
              className="btn btn-small"
              onClick={() => window.location.reload()}
            >
              Rafra&icirc;chir
            </button>
          </div>
        )}

        <div className="dashboard-grid">
          {isAdmin && usage ? (
            <section className="dashboard-card dashboard-card-usage">
              <h2>Espace de stockage</h2>
              <div className="dashboard-metric">
                <span className="dashboard-value">
                  {formatBytes(storedBytes)}
                </span>
                <span className="dashboard-label">utilis&eacute;s</span>
              </div>
              {capacityBytes != null && (
                <>
                  <div className="dashboard-progress">
                    <div
                      className="dashboard-progress-bar"
                      style={{
                        width: `${Math.min(usagePct ?? 0, 100)}%`,
                      }}
                    />
                  </div>
                  <div className="dashboard-metric">
                    <span className="dashboard-value">{usagePct ?? 0}%</span>
                    <span className="dashboard-label">
                      de {formatBytes(capacityBytes)}
                    </span>
                  </div>
                </>
              )}
              <div className="dashboard-metric">
                <span className="dashboard-value">
                  {usage.totals.available_count}
                </span>
                <span className="dashboard-label">objets</span>
              </div>
              <div className="dashboard-metric">
                <span className="dashboard-value">
                  {formatBytes(usage.totals.egress_bytes_month)}
                </span>
                <span className="dashboard-label">&eacute;gress mensuel</span>
              </div>
              <p className="dashboard-muted">
                Mesur&eacute; le{" "}
                {new Date(usage.measured_at * 1000).toLocaleString()}
              </p>
            </section>
          ) : null}

          {isAdmin && stats ? (
            <section className="dashboard-card dashboard-card-stats">
              <h2>Statistiques globales</h2>
              <div className="dashboard-metric">
                <span className="dashboard-value">{stats.applications}</span>
                <span className="dashboard-label">applications</span>
              </div>
              <div className="dashboard-metric">
                <span className="dashboard-value">{stats.spaces}</span>
                <span className="dashboard-label">espaces</span>
              </div>
              <div className="dashboard-metric">
                <span className="dashboard-value">{stats.buckets}</span>
                <span className="dashboard-label">buckets</span>
              </div>
              <div className="dashboard-metric">
                <span className="dashboard-value">
                  {stats.service_identities}
                </span>
                <span className="dashboard-label">identit&eacute;s M2M</span>
              </div>
              <div className="dashboard-metric">
                <span className="dashboard-value">{totalObjects}</span>
                <span className="dashboard-label">objets au total</span>
              </div>
            </section>
          ) : null}

          {!isAdmin ? (
            <section className="dashboard-card dashboard-card-info">
              <h2>Votre espace</h2>
              <p>
                Vous &ecirc;tes connect&eacute; en tant que{" "}
                <strong>{session.data?.role}</strong>. Le tableau de bord complet
                (stockage, quotas, statistiques globales) est r&eacute;serv&eacute;
                aux administrateurs.
              </p>
              <p className="dashboard-muted">
                Utilisez la page Fichiers pour g&eacute;rer vos objets, ou la
                page Transferts pour suivre vos importations en cours.
              </p>
            </section>
          ) : null}
        </div>

        <div className="dashboard-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate({ to: "/" })}
          >
            Aller aux fichiers
          </button>
          {isAdmin && (
            <button
              type="button"
              className="btn btn-small"
              onClick={() => navigate({ to: "/admin" })}
            >
              Administration
            </button>
          )}
          <button
            type="button"
            className="btn btn-small btn-ghost"
            onClick={() => {
              void logout();
              navigate({ to: "/login" });
            }}
          >
            D&eacute;connexion
          </button>
        </div>
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 o";
  const k = 1024;
  const sizes = ["o", "Ko", "Mo", "Go", "To"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}
