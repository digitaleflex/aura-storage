import { Link } from "@tanstack/react-router";
import { VaultMark } from "./VaultMark";
import { useErrorHeadingFocus, useSafeBack } from "../lib/navigation";

/**
 * In-shell fallback: a page crashed but the navigation (sidebar, top bar) is
 * still alive. Rendering the failure *inside* `.content` keeps every way out
 * available — switching page, going back, retrying — so the user is never
 * stranded on an error screen with only a reload.
 */
export function PageError({
  error,
  onReset,
}: {
  error: unknown;
  onReset: () => void;
}) {
  const detail = error instanceof Error ? error.message : String(error);

  const goBack = useSafeBack();
  const headingRef = useErrorHeadingFocus<HTMLHeadingElement>();

  return (
    <section className="route-error route-error-inline" role="alert">
      <div className="route-error-card">
        <span className="route-error-mark">
          <VaultMark size={34} />
        </span>
        <h1 ref={headingRef} tabIndex={-1}>
          Cette page n'a pas pu s'afficher
        </h1>
        <p className="muted">
          Vos fichiers ne sont pas touchés : seul cet écran a rencontré un
          problème. Le reste de l'application fonctionne — réessayez, revenez en
          arrière, ou choisissez une autre page dans le menu.
        </p>
        <div className="route-error-actions">
          <button type="button" className="btn btn-primary" onClick={onReset}>
            Réessayer
          </button>
          <button type="button" className="btn" onClick={goBack}>
            Retour
          </button>
          <Link className="btn" to="/">
            Aller aux fichiers
          </Link>
        </div>
        <details className="route-error-detail">
          <summary>Détail technique</summary>
          <code>{detail}</code>
        </details>
      </div>
    </section>
  );
}
