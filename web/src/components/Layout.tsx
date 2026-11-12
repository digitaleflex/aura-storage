import React from "react";
import { Link, useNavigate, useLocation } from "@tanstack/react-router";
import { useAuth, useSession } from "../lib/auth";
import { hasAdminAccess, api } from "../lib/api";
import { useQuery } from "@tanstack/react-query";
import { VaultMark } from "./VaultMark";
import { StorageUsage } from "./StorageUsage";
import { useTransfers } from "../lib/transferContext";
import { readStorage, writeStorage } from "../lib/safeStorage";
import { hasSeenOnboarding } from "../lib/onboarding";
import { SearchBar } from "./SearchBar";
import { Icon, type IconName } from "./Icon";

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  active: boolean;
  badge?: number;
}

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
  const transfers = useTransfers();

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
    return (readStorage("aura-density") as "comfortable" | "compact") || "comfortable";
  });
  React.useEffect(() => {
    document.body.classList.toggle("density-compact", density === "compact");
    writeStorage("aura-density", density);
  }, [density]);

  // Theme manuel (override prefers-color-scheme)
  const [theme, setTheme] = React.useState<"light" | "dark" | "auto">(() => {
    return (readStorage("aura-theme") as "light" | "dark" | "auto") || "auto";
  });
  React.useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
    writeStorage("aura-theme", theme);
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
    // logout() is best-effort and never rejects: local state is always cleared.
    try {
      await logout();
    } finally {
      await navigate({ to: "/login" });
    }
  }

  // Détermine si on est sur la page "Fichiers" (indexRoute exacte)
  const isFilesPage =
    location.pathname === "/" || location.pathname === "";
  const isTransfersPage = location.pathname === "/transfers";
  const isDiagPage = location.pathname === "/diagnostic";
  const isOnboardingPage = location.pathname === "/onboarding";

  // Rediriger vers l'onboarding si l'utilisateur ne l'a pas encore vu
  React.useEffect(() => {
    if (!session.data) return; // pas encore authentifié
    if (isOnboardingPage) return; // déjà sur l'onboarding
    if (!hasSeenOnboarding()) {
      navigate({ to: "/onboarding" });
    }
  }, [session.data, location.pathname, navigate]);

  // Source unique de la navigation : le menu latéral et le tiroir mobile
  // rendent la même liste (ajouter une page = une ligne ici).
  const navItems: NavItem[] = [
    { to: "/", label: "Fichiers", icon: "folder", active: isFilesPage },
    {
      to: "/transfers",
      label: "Transferts",
      icon: "transfer",
      active: isTransfersPage,
      // Compteur purement décoratif (aria-hidden) : le nom du lien suffit.
      badge: transfers.queue.items.length,
    },
    { to: "/dashboard", label: "Tableau de bord", icon: "dashboard", active: location.pathname === "/dashboard" },
    { to: "/shares", label: "Partages", icon: "share", active: location.pathname === "/shares" },
    { to: "/trash", label: "Corbeille", icon: "trash", active: location.pathname === "/trash" },
    { to: "/diagnostic", label: "Diagnostic réseau", icon: "pulse", active: isDiagPage },
    ...(canAdmin
      ? [{ to: "/admin", label: "Administration", icon: "shield" as const, active: location.pathname === "/admin" }]
      : []),
    { to: "/settings", label: "Paramètres", icon: "settings", active: location.pathname === "/settings" },
    { to: "/help", label: "Aide", icon: "help", active: location.pathname === "/help" },
  ];

  const renderNavLink = (item: NavItem, onNavigate: () => void) => (
    <Link
      key={item.to}
      to={item.to}
      activeOptions={{ exact: true }}
      className={item.active ? "nav-link nav-link-active" : "nav-link"}
      onClick={onNavigate}
    >
      <Icon name={item.icon} />
      {item.label}
      {item.badge ? (
        <span className="nav-badge" aria-hidden="true">
          {item.badge}
        </span>
      ) : null}
    </Link>
  );

  return (
    <div className={`shell${isTransfersPage ? " shell-transfers" : ""}`}>
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
          {navItems.map((item) => renderNavLink(item, () => toggleSidebar(false)))}
        </nav>

        {/* Indicateur de stockage réel (capacité admin uniquement). */}
        <StorageUsage
          usage={usageQuery.data}
          loading={usageQuery.isLoading}
          formatBytes={formatBytes}
        />
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
                <Icon name="close" />
              </button>
            </div>
            <nav className="mobile-drawer-nav" aria-label="Navigation mobile">
              {navItems.map((item) => renderNavLink(item, () => closeMobile(false)))}
            </nav>
            <StorageUsage
              usage={usageQuery.data}
              loading={usageQuery.isLoading}
              formatBytes={formatBytes}
            />
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
            <Icon name="menu" />
          </button>
          {/* Bouton de togglage sidebar (réduire/agrandir) sur grand écran */}
          <button
            className="btn btn-ghost btn-small topbar-sidebar-toggle"
            aria-label={sidebarCollapsed ? "Agrandir la sidebar" : "Réduire la sidebar"}
            aria-pressed={sidebarCollapsed}
            onClick={() => toggleSidebar(!sidebarCollapsed)}
          >
            <Icon name="sidebar" />
          </button>
          {/* Recherche globale : au centre de la barre du haut, sur toutes les pages. */}
          <div className="topbar-search" role="search" aria-label="Recherche globale">
            <SearchBar alwaysOpen={false} />
          </div>
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
                  <Icon name={density === "compact" ? "density-compact" : "density-comfortable"} />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  aria-label="Changer le thème"
                  onClick={() =>
                    setTheme((t) => (t === "dark" ? "light" : t === "light" ? "auto" : "dark"))
                  }
                >
                  <Icon name={theme === "dark" ? "moon" : theme === "light" ? "sun" : "monitor"} />
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