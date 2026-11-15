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

  return (
    <div className="settings-page" data-testid="settings-page">
      <ToastStack
        toasts={toasts}
        onDismiss={(id: number) =>
          setToasts((current) => current.filter((t) => t.id !== id))
        }
      />
      <div className="settings-shell">
        <VaultMark />
        <div className="settings-header">
          <h1>Paramètres</h1>
          <p className="settings-subtitle muted">
            Compte de {user?.name ?? "utilisateur"}
          </p>
        </div>

        <section className="settings-card" aria-labelledby="settings-account-title">
          <h2 id="settings-account-title">Compte</h2>
          <table className="settings-table">
            <tbody>
              <tr>
                <th scope="row">Nom d'utilisateur</th>
                <td>{user?.name ?? "—"}</td>
              </tr>
              <tr>
                <th scope="row">Rôle</th>
                <td>
                  {user?.role === "admin"
                    ? "Administrateur"
                    : user?.role === "operator"
                      ? "Opérateur"
                      : "Utilisateur"}
                </td>
              </tr>
              <tr>
                <th scope="row">Type de session</th>
                <td>
                  {user?.kind === "service"
                    ? "Identité de service"
                    : "Session humaine (cookie)"}
                </td>
              </tr>
              <tr>
                <th scope="row">Espace</th>
                <td>{user?.space_id ?? "—"}</td>
              </tr>
            </tbody>
          </table>
          <p className="settings-muted muted">
            Le changement de mot de passe n'est pas encore exposé via l'API
            publique. Contactez un administrateur pour réinitialiser votre mot de
            passe.
          </p>
        </section>

        <section className="settings-card" aria-labelledby="settings-preferences-title">
          <h2 id="settings-preferences-title">Préférences</h2>
          <label className="settings-field">
            <input
              type="checkbox"
              checked={darkMode}
              onChange={handleToggleDark}
            />
            Thème sombre
          </label>
          <p className="settings-muted muted">
            La préférence est mémorisée dans votre navigateur (localStorage).
          </p>
        </section>

        <section className="settings-card settings-card-danger" aria-labelledby="settings-session-title">
          <h2 id="settings-session-title">Session</h2>
          <button
            type="button"
            className="btn btn-danger"
            disabled={saving}
            aria-label="Se déconnecter d'AURA Vault"
            onClick={handleLogout}
          >
            {saving ? "Déconnexion…" : "Se déconnecter"}
          </button>
          <p className="settings-muted muted">
            Votre session sera supprimée. Vous devrez vous reconnecter.
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
