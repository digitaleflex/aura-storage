import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(username, password);
      await navigate({ to: "/" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Invalid credentials. Access is rejected.");
      } else {
        setError("Login failed: service unavailable or network error.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="card">
      <h1>Log in</h1>
      <p className="muted">Session is cookie-based; no secrets are stored in the browser.</p>
      <form onSubmit={handleSubmit} className="form">
        <label className="field">
          <span>Username</span>
          <input
            type="text"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error ? <p role="alert" className="alert alert-error">{error}</p> : null}
        <button type="submit" className="btn btn-primary" disabled={pending}>
          {pending ? "Logging in…" : "Log in"}
        </button>
      </form>
    </section>
  );
}
