import { Link, useNavigate } from "@tanstack/react-router";
import { useAuth, useSession } from "../lib/auth";
import { hasAdminAccess } from "../lib/api";
import { VaultMark } from "./VaultMark";

export function Layout({ children }: { children: React.ReactNode }) {
  const { csrf, logout } = useAuth();
  const session = useSession();
  const navigate = useNavigate();

  const canAdmin = hasAdminAccess(session.data?.role);

  async function handleLogout() {
    await logout();
    await navigate({ to: "/login" });
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <Link to="/" className="brand">
          <VaultMark />
          AURA Vault
        </Link>
        <nav className="nav" aria-label="Navigation principale">
          <Link to="/" activeOptions={{ exact: true }}>
            Fichiers
          </Link>
          {canAdmin ? <Link to="/admin">Administration</Link> : null}
        </nav>
        <span className="spacer" />
        {csrf ? (
          <>
            <span className="whoami">Coffre déverrouillé</span>
            <nav className="nav" aria-label="Session">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => void handleLogout()}
              >
                Déconnexion
              </button>
            </nav>
          </>
        ) : (
          <nav className="nav" aria-label="Session">
            <Link to="/login">Connexion</Link>
          </nav>
        )}
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
