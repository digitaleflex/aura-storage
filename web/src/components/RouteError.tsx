import { Link, useRouter } from "@tanstack/react-router";
import { VaultMark } from "./VaultMark";
import { useErrorHeadingFocus, useSafeBack } from "../lib/navigation";

/**
 * Shown when a page throws while rendering (a malformed API answer, a bug).
 * Replaces the router's default English, unstyled "Something went wrong!".
 *
 * Navigation stays inside the SPA whenever possible: the user must be able to
 * retry, go back where they came from, or reach the files page without a full
 * reload (which would lose their filters and scroll position, and breaks on
 * subpath deployments when using a hard `/` link).
 */
export function RouteError({ error, reset }: { error: unknown; reset?: () => void }) {
  const router = useRouter();
  const detail = error instanceof Error ? error.message : String(error);

  const retry = reset ?? (() => void router.invalidate());
  const goBack = useSafeBack();
  const headingRef = useErrorHeadingFocus<HTMLHeadingElement>();

  return (
    <main className="route-error" role="alert">
      <div className="route-error-card">
        <span className="route-error-mark">
          <VaultMark size={34} />
        </span>
        <h1 ref={headingRef} tabIndex={-1}>
          Cette page n'a pas pu s'afficher
        </h1>
        <p className="muted">
          Vos fichiers ne sont pas touchés : seul l'affichage a rencontré un problème.
          Réessayez, revenez en arrière, ou rejoignez vos fichiers — le reste de
          l'application reste utilisable.
        </p>
        <div className="route-error-actions">
          <button type="button" className="btn btn-primary" onClick={retry}>
            Réessayer
          </button>
          <button type="button" className="btn" onClick={goBack}>
            Retour
          </button>
          <Link className="btn" to="/">
            Aller aux fichiers
          </Link>
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => window.location.reload()}
          >
            Recharger la page
          </button>
        </div>
        <details className="route-error-detail">
          <summary>Détail technique</summary>
          <code>{detail}</code>
        </details>
      </div>
    </main>
  );
}

/** Unknown URL (a stale bookmark, a truncated link): never a dead end. */
export function RouteNotFound() {
  const goBack = useSafeBack();
  const headingRef = useErrorHeadingFocus<HTMLHeadingElement>();

  return (
    <main className="route-error" role="alert">
      <div className="route-error-card">
        <span className="route-error-mark">
          <VaultMark size={34} />
        </span>
        <p className="muted">Erreur 404</p>
        <h1 ref={headingRef} tabIndex={-1}>
          Cette page n'existe pas
        </h1>
        <p className="muted">
          Le lien est peut-être incomplet ou l'adresse a changé. Revenez en
          arrière, ou rejoignez vos fichiers pour continuer.
        </p>
        <div className="route-error-actions">
          <button type="button" className="btn btn-primary" onClick={goBack}>
            Retour
          </button>
          <Link className="btn" to="/">
            Aller aux fichiers
          </Link>
        </div>
      </div>
    </main>
  );
}
