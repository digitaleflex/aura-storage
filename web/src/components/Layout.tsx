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
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            <VaultMark />
            <span className="brand-name">AURA Vault</span>
          </Link>
          <nav className="nav" aria-label="Navigation principale">
            <Link to="/" activeOptions={{ exact: true }}>
              Fichiers
            </Link>
            {canAdmin ? <Link to="/admin">Administration</Link> : null}
          </nav>
          <div className="session">
            {csrf ? (
              <>
                <span className="whoami">Coffre déverrouillé</span>
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  onClick={() => void handleLogout()}
                >
                  Déconnexion
                </button>
              </>
            ) : (
              <Link to="/login">Connexion</Link>
            )}
          </div>
        </div>
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
