import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Error boundary: captures unhandled render errors and shows a fallback
 * instead of crashing the whole application. Logs the error to console
 * (never to the server — no sensitive data).
 *
 * Two uses:
 * - top level (main.tsx): no props, full-page fallback. The router is not
 *   mounted below it yet, so navigation is a real browser navigation.
 * - inside the app shell (`Layout`): pass `resetKey` (the current location) so
 *   navigating anywhere clears the error and renders the new page normally,
 *   and a `fallback` that can use router hooks.
 */
type ErrorBoundaryProps = {
  children: ReactNode;
  /** Changing this value clears the captured error (e.g. on navigation). */
  resetKey?: unknown;
  fallback?: (error: Error, reset: () => void) => ReactNode;
};

type ErrorBoundaryState = {
  hasError: boolean;
  error: Error | null;
  resetKey: unknown;
};

/** Vite base path: "/" or the deployment subpath (e.g. "/app/"). */
function appBaseUrl(): string {
  return import.meta.env.BASE_URL || "/";
}

function GlobalErrorFallback({
  detail,
  onReset,
}: {
  detail: string;
  onReset: () => void;
}) {
  return (
    <div
      role="alert"
      style={{
        padding: "2rem",
        textAlign: "center",
        color: "var(--ink)",
      }}
    >
      <h1>Une erreur est survenue</h1>
      <p className="muted">
        L'application a rencontré un problème inattendu. Vous pouvez réessayer
        sans perdre l'adresse en cours, ou rejoindre vos fichiers. Vos fichiers
        ne sont pas touchés.
      </p>
      <div className="route-error-actions">
        <button type="button" className="btn btn-primary" onClick={onReset}>
          Réessayer
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => window.location.assign(appBaseUrl())}
        >
          Aller aux fichiers
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={() => window.location.reload()}
        >
          Recharger la page
        </button>
      </div>
      <details className="route-error-detail" style={{ maxWidth: 520, margin: "0 auto" }}>
        <summary>Détail technique</summary>
        <code>{detail}</code>
      </details>
    </div>
  );
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
    error: null,
    resetKey: this.props.resetKey,
  };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  // Navigation is the natural way out of a broken page: a new location means a
  // fresh render, so the boundary must not keep showing the old failure.
  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: ErrorBoundaryState,
  ): Partial<ErrorBoundaryState> | null {
    if (props.resetKey !== state.resetKey) {
      return { hasError: false, error: null, resetKey: props.resetKey };
    }
    return null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log to console only — never to the server (no sensitive data).
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    const { error, hasError } = this.state;
    if (hasError) {
      const detail = error instanceof Error ? error.message : String(error);
      if (this.props.fallback) {
        return this.props.fallback(error ?? new Error(detail), this.reset);
      }
      return <GlobalErrorFallback detail={detail} onReset={this.reset} />;
    }
    return this.props.children;
  }
}
