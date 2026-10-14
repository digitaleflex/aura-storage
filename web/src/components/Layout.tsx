import { Link, useNavigate } from "@tanstack/react-router";
import { useAuth } from "../lib/auth";
import { VaultMark } from "./VaultMark";

export function Layout({ children }: { children: React.ReactNode }) {
  const { csrf, logout } = useAuth();
  const navigate = useNavigate();

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
