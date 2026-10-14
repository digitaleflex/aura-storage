import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../lib/auth";

export function LoginPage() {
  const { loginWithGoogle } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await loginWithGoogle();
    } catch {
      setError("Google sign-in could not start. Please retry.");
      setPending(false);
    }
  }

  return (
    <section className="card">
      <h1>Log in</h1>
      <p className="muted">
        Sign in with your Google account. Sessions are cookie-based; no
        passwords and no storage keys are handled by this interface.
      </p>
      <form onSubmit={(e) => void handleSubmit(e)} className="form">
        <button type="submit" className="btn btn-primary" disabled={pending}>
          {pending ? "Redirecting…" : "Sign in with Google"}
        </button>
      </form>
      {error ? (
        <p role="alert" className="alert alert-error">
          {error}
        </p>
      ) : null}
    </section>
  );
}
