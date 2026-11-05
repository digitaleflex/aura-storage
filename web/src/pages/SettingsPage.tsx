import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useAuth, useSession } from "../lib/auth";
import { describeError } from "../lib/errors";
import { VaultMark } from "../components/VaultMark";
import { ToastStack, makeToast, type Toast } from "../components/Toasts";

export function SettingsPage() {
  const { logout } = useAuth();
  const session = useSession();
  const navigate = useNavigate();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [darkMode, setDarkMode] = useState(
    () => document.documentElement.dataset.theme === "dark",
  );
  const [saving, setSaving] = useState(false);

  function notify(kind: Toast["kind"], text: string) {
    setToasts((current) => [...current.slice(-3), makeToast(kind, text)]);
  }

  function handleToggleDark() {
    const next = !darkMode;
    setDarkMode(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    localStorage.setItem("aura-theme", next ? "dark" : "light");
    notify("ok", next ? "Thème sombre activé." : "Thème clair activé.");
  }

  async function handleLogout() {
    setSaving(true);
    try {
      await logout();
      navigate({ to: "/login" });
    } catch (err) {
      notify("error", describeError(err, "Déconnexion impossible."));
    } finally {
      setSaving(false);
    }
  }

  const user = session.data;
  const isDark = document.documentElement.dataset.theme === "dark";

  return (
    <div className="settings-page" data-testid="settings-page">
      <ToastStack toasts={toasts} onDismiss={(id: number) =>
        setToasts((current) => current.filter((t) => t.id !== id))
      } />
      <div className="settings-shell">
        <VaultMark />
        <div className="settings-header">
          <h1>Paramètres</h1>
          <p className="settings-subtitle">
            Compte de {user?.name ?? "utilisateur"}
          </p>
        </div>

        <section className="settings-card">
          <h2>Compte</h2>
          <table>
            <tbody>
              <tr>
                <td>Nom d'utilisateur</td>
                <td>{user?.name ?? "—"}</td>
              </tr>
              <tr>
                <td>Rôle</td>
                <td>
                  {user?.role === "admin"
                    ? "Administrateur"
                    : user?.role === "operator"
                      ? "Opérateur"
                      : "Utilisateur"}
                </td>
              </tr>
              <tr>
                <td>Type de session</td>
                <td>
                  {user?.kind === "service"
                    ? "Identité de service"
                    : "Session humaine (cookie)"}
                </td>
              </tr>
              <tr>
                <td>Espace</td>
                <td>{user?.space_id ?? "—"}</td>
              </tr>
            </tbody>
          </table>
          <p className="settings-muted">
            Le changement de mot de passe n'est pas encore expos&eacute; via
            l'API publique. Contactez un administrateur pour r&eacute;initialiser
            votre mot de passe.
          </p>
        </section>

        <section className="settings-card">
          <h2>Préférences</h2>
          <label className="settings-field">
            <input
              type="checkbox"
              checked={isDark}
              onChange={handleToggleDark}
            />
            Thème sombre
          </label>
          <p className="settings-muted">
            La préférence est m&eémorisée dans votre navigateur (localStorage).
          </p>
        </section>

        <section className="settings-card settings-card-danger">
          <h2>Session</h2>
          <button
            type="button"
            className="btn btn-danger"
            disabled={saving}
            onClick={handleLogout}
          >
            {saving ? "Déconnexion…" : "Se déconnecter"}
          </button>
          <p className="settings-muted">
            Votre session sera supprim&eacute;e. Vous devrez vous reconnecter.
          </p>
        </section>

        <div className="settings-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate({ to: "/" })}
          >
            Aller aux fichiers
          </button>
        </div>
      </div>
    </div>
  );
}
