import { Link, useNavigate, useLocation } from "@tanstack/react-router";
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
 * - Largeur contrôlée par le token --side-w (248px par défaut).
 * - État actif géré par le routeur TanStack + classe .nav-link-active.
 * - Collapsible : bouton en topbar + mémorisation en URL (?sidebar=collapsed).
 * - S'ouvre/referme sur clic de lien dans la sidebar mobile.
 */
export function Layout({ children }: { children: React.ReactNode }) {
  const { csrf, logout } = useAuth();
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();

  const canAdmin = hasAdminAccess(session.data?.role);

  // État collapsible : persistant en URL (?sidebar=collapsed|expanded)
  const urlParams = new URLSearchParams(location.search);
  const sidebarCollapsed = urlParams.get("sidebar") === "collapsed";

  // Mise à jour de l'URL lors du toggle
  const toggleSidebar = (collapsed: boolean) => {
    const search = new URLSearchParams(location.search);
    search.set("sidebar", collapsed ? "collapsed" : "expanded");
    const newSearch = search.toString();
    // Remplace les params existants mais garde d'autres éventuels
    const updatedSearch =
      location.search === newSearch ? "" : newSearch;
    navigate({ to: location.pathname, search: updatedSearch });
  };

  async function handleLogout() {
    await logout();
    await navigate({ to: "/login" });
  }

  // Détermine si on est sur la page "Fichiers" (indexRoute exacte)
  const isFilesPage =
    location.pathname === "/" || location.pathname === "";

  return (
    <div className="shell">
      <aside
        className={`sidebar${sidebarCollapsed ? " sidebar-collapsed" : ""}`}
        aria-label="Barre latérale AURA Vault"
      >
        {/* Brand section — réduit à l'icône quand collapsed */}
        <Link to="/" className="brand">
          <VaultMark />
          <span
            aria-label={sidebarCollapsed ? "AURA Vault" : undefined}
          >
            AURA Vault
          </span>
        </Link>

        {/* Navigation principale */}
        <nav className="nav" aria-label="Navigation principale">
          {/* Élément : Fichiers — état actif via classe .nav-link-active */}
          <Link
            to="/"
            activeOptions={{ exact: true }}
            className={isFilesPage ? "nav-link nav-link-active" : "nav-link"}
            onClick={() => toggleSidebar(false)}
          >
            <svg
              aria-hidden="true"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
            >
              <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
            </svg>
            Fichiers
          </Link>
          {canAdmin ? (
            <Link
              to="/admin"
              activeOptions={{ exact: true }}
              className={
                location.pathname === "/admin" ? "nav-link nav-link-active" : "nav-link"
              }
              onClick={() => toggleSidebar(false)}
            >
              <svg
                aria-hidden="true"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              >
                <path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3Z" />
              </svg>
              Administration
            </Link>
          ) : null}
        </nav>

        {/* Indicateur de stockage — placeholder honnête */}
        <p className="sidebar-foot">
          <svg
            aria-hidden="true"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
          >
            <rect x="5" y="11" width="14" height="10" rx="2" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" />
          </svg>
          <span>
            {/* TODO : remplacer par donnée usage réelle depuis /api/v1/admin/usage */}
            Stockage : --:-- utilisé
          </span>
        </p>
      </aside>
      <div className="main">
        <header className="topbar">
          {/* Bouton de togglage sidebar uniquement sur grand écran */}
          {sidebarCollapsed ? null : (
            <button
              className="btn btn-ghost btn-small topbar-sidebar-toggle"
              aria-label="Réduire la sidebar"
              onClick={() => toggleSidebar(true)}
            >
              <svg
                aria-hidden="true"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              >
                <path d="M3 12h18M3 6h18M3 18h18" />
              </svg>
            </button>
          )}
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