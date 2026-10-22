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
 * Paramètres de recherche portés par le shell.
 *
 * Les routes du shell ne déclarent pas de `validateSearch` : on type donc
 * explicitement la seule clé lue ici, plutôt que de laisser le `{}` du
 * routeur (ou un `any`) diffuser dans le composant.
 */
type ShellSearch = { sidebar?: string };

/**
 * App shell: a dark navigation sidebar (stacks above the content on a phone)
 * and a light top bar that says who is signed in. Pages render in `.content`.
 * - Largeur contrôlée par le token --side-w (248px par défaut).
 * - État actif géré par le routeur TanStack + classe .nav-link-active.
 * - Collapsible : bouton en topbar + état porté par l'URL (`?sidebar=collapsed`
 *   ; la clé est absente quand la barre est étendue — l'URL reste propre).
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

  // État collapsible : la source de vérité est l'URL (état partageable, lien
  // profond). `location.search` est l'objet de paramètres *analysé* par le
  // routeur — le comparer à une chaîne, ou le renvoyer au routeur sous forme
  // de chaîne, le faisait échouer : le paramètre ne revenait jamais et la
  // barre ne se repliait pas.
  const shellSearch = location.search as ShellSearch;
  const sidebarCollapsed = shellSearch.sidebar === "collapsed";

  // Mobile drawer state
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const touchStartX = React.useRef<number | null>(null);

  // Densité d'affichage (compact/confortable)
  const [density, setDensity] = React.useState<"comfortable" | "compact">(() => {
    return (localStorage.getItem("aura-density") as "comfortable" | "compact") || "comfortable";
  });
  React.useEffect(() => {
    document.body.classList.toggle("density-compact", density === "compact");
    localStorage.setItem("aura-density", density);
  }, [density]);

  // Theme manuel (override prefers-color-scheme)
  const [theme, setTheme] = React.useState<"light" | "dark" | "auto">(() => {
    return (localStorage.getItem("aura-theme") as "light" | "dark" | "auto") || "auto";
  });
  React.useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
    localStorage.setItem("aura-theme", theme);
  }, [theme]);
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

  /**
   * Replie ou déplie la barre latérale en portant l'état dans l'URL.
   *
   * Convention : `?sidebar=collapsed` matérialise le repli, l'absence de la
   * clé vaut l'état par défaut (barre étendue). On n'écrit jamais
   * `?sidebar=expanded` : une URL partagée reste lisible et le paramètre
   * n'apparaît que lorsqu'il porte une information.
   *
   * `search` est fourni sous forme fonctionnelle : le routeur attend un
   * objet (une chaîne y serait sérialisée caractère par caractère) et la
   * forme fonctionnelle préserve les autres paramètres de la requête au lieu
   * de les écraser. La clé repart à `undefined` — et non supprimée de
   * l'objet — parce que le routeur sérialise l'objet renvoyé tel quel : une
   * clé `undefined` est omise de l'URL.
   */
  const toggleSidebar = (collapsed: boolean) => {
    void navigate({
      to: location.pathname,
      search: (prev) => {
        const next: ShellSearch = { ...(prev as ShellSearch) };
        next.sidebar = collapsed ? "collapsed" : undefined;
        return next;
      },
    });
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
      <a className="skip-link" href="#main-content">
        Aller au contenu principal
      </a>
      <aside
        className={`sidebar${sidebarCollapsed ? " sidebar-collapsed" : ""}`}
        aria-label="Barre latérale AURA Vault"
      >
        {/* Brand section — réduit à l'icône quand collapsed. Le lien porte
            lui-même son nom accessible (« AURA Vault ») : le libellé visible
            peut donc être masqué sans que la marque perde son identité pour un
            lecteur d'écran. Le masquage passe par `font-size: 0`
            (`.brand-name-hidden`), pas par `display: none` : le texte reste
            dans l'arbre d'accessibilité. */}
        <Link to="/" className="brand" aria-label="AURA Vault">
          <VaultMark />
          <span className={sidebarCollapsed ? "brand-name-hidden" : undefined}>
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
          <span aria-live="polite" aria-atomic="true">
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
            onTouchStart={(event) => {
              touchStartX.current = event.touches[0]?.clientX ?? null;
            }}
            onTouchEnd={(event) => {
              const start = touchStartX.current;
              touchStartX.current = null;
              if (start === null) return;
              const end = event.changedTouches[0]?.clientX ?? start;
              if (start - end > 60) closeMobile();
            }}
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
              <span aria-live="polite" aria-atomic="true">
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
                  aria-label="Changer la densité d'affichage"
                  onClick={() => setDensity((d) => (d === "compact" ? "comfortable" : "compact"))}
                >
                  {density === "compact" ? " ≡ " : " ☰ "}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  aria-label="Changer le thème"
                  onClick={() =>
                    setTheme((t) => (t === "dark" ? "light" : t === "light" ? "auto" : "dark"))
                  }
                >
                  {theme === "dark" ? "🌙" : theme === "light" ? "☀️" : "💻"}
                </button>
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
        <main id="main-content" className="content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}