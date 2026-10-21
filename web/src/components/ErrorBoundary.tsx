import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Error boundary: captures unhandled render errors and shows a fallback
 * instead of crashing the whole application. Logs the error to console
 * (never to the server — no sensitive data).
 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log to console only — never to the server (no sensitive data).
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
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
            L'application a rencontré un problème inattendu. Rechargez la page
            ou réessayez plus tard.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => window.location.reload()}
          >
            Recharger la page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}