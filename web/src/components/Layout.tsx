import React from "react";
import { Link, useNavigate, useLocation } from "@tanstack/react-router";
import { useAuth, useSession } from "../lib/auth";
import { hasAdminAccess, api } from "../lib/api";
import { useQuery } from "@tanstack/react-query";
import { VaultMark } from "./VaultMark";

/** Local copy of formatBytes to avoid circular import with ObjectsPage. */
function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return "taille inconnue";
  if (size === 0) return "0 o";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  const value = size / 1024 ** index;
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

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
  // Display name of the signed-in account (username for a human, identity
  // name for a service). It must come from the session: an unbound `name`
  // silently resolves to the global `window.name`, i.e. an empty string, and
  // the top bar showed a blank name instead of the account.
  const name = session.data?.name;

  // Usage réel pour l'indicateur de stockage (admin uniquement)
  const usageQuery = useQuery({
    queryKey: ["admin", "usage"],
    queryFn: () => api.adminUsage(),
    enabled: canAdmin,
    retry: false,
  });

  // État collapsible : persistant en URL (?sidebar=collapsed|expanded)
  const urlParams = new URLSearchParams(location.search);
  const sidebarCollapsed = urlParams.get("sidebar") === "collapsed";

  // Mobile drawer state
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const hamburgerRef = React.useRef<HTMLButtonElement | null>(null);
  const drawerRef = React.useRef<HTMLDivElement | null>(null);
  const drawerCloseRef = React.useRef<HTMLButtonElement | null>(null);

  /** Close the drawer and give focus back to the button that opened it. */
  function closeMobile(restoreFocus = true) {
    setMobileOpen(false);
    if (restoreFocus) {
      requestAnimationFrame(() => hamburgerRef.current?.focus());
    }
  }

  // Close mobile drawer on route change (no focus restore: the destination
  // owns focus after navigation).
  React.useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  // Focus trap for the mobile drawer: opening moves focus inside, Tab and
  // Shift+Tab cycle within it, Escape closes and restores the trigger.
  React.useEffect(() => {
    if (!mobileOpen) return;
    drawerCloseRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusables = () =>
      Array.from(
        drawerRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.offsetParent !== null);

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMobile();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !drawerRef.current?.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileOpen]);

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
            {usageQuery.data
              ? `Stockage : ${formatBytes(usageQuery.data.totals.stored_bytes).replace(" ", "")} utilisés`
              : canAdmin
                ? "Stockage : chargement…"
                : "Chiffré au repos, intégrité vérifiée"}
          </span>
        </p>
      </aside>

      {/* Mobile drawer overlay */}
      {mobileOpen ? (
        <>
          <div
            className="mobile-drawer-scrim"
            onClick={() => closeMobile()}
            aria-hidden="true"
          />
          <div
            ref={drawerRef}
            id="mobile-navigation"
            className="mobile-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation mobile"
          >
            <div className="mobile-drawer-head">
              <Link to="/" className="brand" onClick={() => closeMobile(false)}>
                <VaultMark />
                <span className="brand-name">AURA Vault</span>
              </Link>
              <button
                ref={drawerCloseRef}
                className="btn btn-ghost btn-small"
                aria-label="Fermer le menu"
                onClick={() => closeMobile()}
              >
                ✕
              </button>
            </div>
            <nav className="mobile-drawer-nav" aria-label="Navigation mobile">
              <Link
                to="/"
                activeOptions={{ exact: true }}
                className={isFilesPage ? "nav-link nav-link-active" : "nav-link"}
                onClick={() => closeMobile(false)}
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
                  onClick={() => closeMobile(false)}
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
                {usageQuery.data
                  ? `Stockage : ${formatBytes(usageQuery.data.totals.stored_bytes)} utilisés`
                  : "Chiffré au repos, intégrité vérifiée"}
              </span>
            </p>
          </div>
        </>
      ) : null}

      <div className="main">
        <header className="topbar">
          {/* Bouton hamburger mobile */}
          <button
            ref={hamburgerRef}
            className="btn btn-ghost btn-small topbar-mobile-toggle"
            aria-label="Ouvrir le menu de navigation"
            aria-expanded={mobileOpen}
            aria-controls="mobile-navigation"
            onClick={() => setMobileOpen(true)}
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
          {/* Bouton de togglage sidebar (réduire/agrandir) sur grand écran */}
          <button
            className="btn btn-ghost btn-small topbar-sidebar-toggle"
            aria-label={sidebarCollapsed ? "Agrandir la sidebar" : "Réduire la sidebar"}
            aria-pressed={sidebarCollapsed}
            onClick={() => toggleSidebar(!sidebarCollapsed)}
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