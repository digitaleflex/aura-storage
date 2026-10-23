import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ApiError } from "../lib/api";
import { describeError } from "../lib/errors";
import { useAuth } from "../lib/auth";
import { consumeLoginRedirect } from "../lib/loginRedirect";
import { VaultMark } from "../components/VaultMark";

const GUARANTEES = [
  "Chiffrement au repos, appliqué à chaque fichier",
  "Taille et empreinte SHA-256 contrôlées à chaque import",
  "Journal d'audit de toutes les actions",
];

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(username, password);
      const target = consumeLoginRedirect();
      if (target) {
        // Full navigation: re-reads /me and restores the page the guard left.
        window.location.assign(target);
      } else {
        await navigate({ to: "/" });
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Identifiants invalides. Accès refusé.");
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Trop de tentatives. Patientez une minute puis réessayez.");
      } else {
        setError(describeError(err, "Connexion impossible : service indisponible."));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="login-wrap">
      <section className="login-intro" aria-label="Présentation">
        <div className="login-brand">
          <VaultMark size={30} />
          <span>AURA Vault</span>
        </div>
        <div className="login-pitch">
          <h2>Vos fichiers, chiffrés et vérifiés.</h2>
          <p>
            Un fichier n'est déclaré disponible qu'une fois sa taille et son empreinte
            contrôlées par le serveur.
          </p>
        </div>
        <ul className="login-points">
          {GUARANTEES.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </section>
      <section className="login-card" aria-labelledby="login-title">
        <h1 id="login-title">Connexion</h1>
        <p className="muted">Identifiez-vous pour accéder au coffre.</p>
        {error ? (
          <p role="alert" className="alert alert-error">
            {error}
          </p>
        ) : null}
        <form onSubmit={(e) => void handleSubmit(e)} className="form">
          <label className="field">
            <span>Identifiant</span>
            <input
              type="text"
              name="username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <div className="field">
            <label htmlFor="login-password">Mot de passe</label>
            <div className="password-row">
              <input
                id="login-password"
                type={showPassword ? "text" : "password"}
                name="password"
                autoComplete="current-password"
                aria-invalid={error ? true : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="btn btn-ghost btn-small"
                aria-pressed={showPassword}
                onClick={() => setShowPassword((value) => !value)}
              >
                {showPassword ? "Masquer" : "Afficher"}
              </button>
            </div>
          </div>
          <button type="submit" className="btn btn-primary btn-block" disabled={pending}>
            {pending ? "Connexion…" : "Se connecter"}
          </button>
        </form>
        <p className="muted login-note">
          Après plusieurs essais infructueux, la connexion est temporairement suspendue.
        </p>
      </section>
    </div>
  );
}
