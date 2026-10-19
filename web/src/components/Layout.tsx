import { Link, useNavigate } from "@tanstack/react-router";
import { useAuth, useSession } from "../lib/auth";
import { hasAdminAccess } from "../lib/api";
import { VaultMark } from "./VaultMark";

/** Human label for a session role (the API stays authoritative on access). */
function roleLabel(kind: string | undefined, role: string | null | undefined): string {
  if (kind === "service") return "Identité de service";
  if (role === "admin") return "Administrateur";
  if (role === "operator") return "Opérateur";
  return "Utilisateur";
}

/** Two-letter initials for the account chip; never derived from a pronoun. */
function initials(name: string): string {
  const letters = name.replace(/[^\p{L}\p{N}]/gu, "");
  return (letters.slice(0, 2) || "?").toUpperCase();
}

/**
 * App shell: a dark navigation sidebar (stacks above the content on a phone)
 * and a light top bar that says who is signed in. Pages render in `.content`.
 */
export function Layout({ children }: { children: React.ReactNode }) {
  const { csrf, logout } = useAuth();
  const session = useSession();
  const navigate = useNavigate();

  const canAdmin = hasAdminAccess(session.data?.role);
  const name = session.data?.name ?? null;

  async function handleLogout() {
    await logout();
    await navigate({ to: "/login" });
  }

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Barre latérale">
        <Link to="/" className="brand">
          <VaultMark />
          <span className="brand-name">AURA Vault</span>
        </Link>
        <nav className="nav" aria-label="Navigation principale">
          <Link to="/" activeOptions={{ exact: true }}>
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
            </svg>
            Fichiers
          </Link>
          {canAdmin ? (
            <Link to="/admin">
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3Z" />
              </svg>
              Administration
            </Link>
          ) : null}
        </nav>
        <p className="sidebar-foot">
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="5" y="11" width="14" height="10" rx="2" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" />
          </svg>
          Chiffré au repos, intégrité vérifiée à l'import
        </p>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="session">
            {csrf ? (
              <>
                <span className="whoami">
                  <span className="avatar" aria-hidden="true">
                    {initials(name ?? "")}
                  </span>
                  <span className="whoami-text">
                    <span className="whoami-name">{name ?? "Session ouverte"}</span>
                    <span className="whoami-role">
                      {roleLabel(session.data?.kind, session.data?.role)}
                    </span>
                  </span>
                </span>
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
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
