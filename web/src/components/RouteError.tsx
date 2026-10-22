import { VaultMark } from "./VaultMark";

/** Shown when a page throws while rendering (a malformed API answer, a bug).
 * Replaces the router's default English, unstyled "Something went wrong!". */
export function RouteError({ error }: { error: unknown }) {
  const detail = error instanceof Error ? error.message : String(error);
  return (
    <main className="route-error" role="alert">
      <div className="route-error-card">
        <span className="route-error-mark">
          <VaultMark size={34} />
        </span>
        <h1>Cette page n'a pas pu s'afficher</h1>
        <p className="muted">
          Vos fichiers ne sont pas touchés : seul l'affichage a rencontré un problème.
          Rechargez la page ; si cela se reproduit, transmettez le détail ci-dessous à
          l'administrateur.
        </p>
        <div className="route-error-actions">
          <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
            Recharger la page
          </button>
          <a className="btn" href="/">
            Retour aux fichiers
          </a>
        </div>
        <details className="route-error-detail">
          <summary>Détail technique</summary>
          <code>{detail}</code>
        </details>
      </div>
    </main>
  );
}
