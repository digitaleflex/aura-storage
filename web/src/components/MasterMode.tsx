import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../lib/api";
import { useSession } from "../lib/auth";
import { Dialog } from "./Dialog";

/** Seconds left in master mode for this session (0 when inactive), ticking. */
export function useMasterMode(): { active: boolean; secondsLeft: number } {
  const session = useSession();
  const until = session.data?.master_until ?? null;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!until) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [until]);
  const secondsLeft = until ? Math.max(0, Math.floor(until - now / 1000)) : 0;
  return { active: secondsLeft > 0, secondsLeft };
}

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Messages a person can act on, instead of raw API details. */
function masterError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "Mot de passe incorrect.";
    if (err.status === 429) return "Trop de tentatives. Réessayez dans une minute.";
    if (err.status === 0 || err.status >= 500) return "Serveur injoignable. Réessayez dans un instant.";
  }
  return "Activation impossible. Réessayez.";
}

/**
 * Password step-up into master mode: bulk purges and emptying the trash run
 * without a confirmation per item until the timer runs out.
 */
export function MasterModeDialog({
  open,
  csrf,
  onClose,
}: {
  open: boolean;
  csrf: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setPassword("");
      setError(null);
    }
  }, [open]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!csrf || pending) return;
    setPending(true);
    setError(null);
    try {
      await api.enableMasterMode(password, csrf);
      await queryClient.invalidateQueries({ queryKey: ["session"] });
      onClose();
    } catch (err) {
      setError(masterError(err));
    } finally {
      setPending(false);
      setPassword("");
    }
  }

  return (
    <Dialog open={open} title="Activer le mode maître" onClose={onClose}>
      <form className="stack" onSubmit={(e) => void submit(e)}>
        <p className="muted">
          Pendant 15 minutes, les purges définitives en masse et le vidage de la corbeille
          s'exécutent sans confirmation fichier par fichier. Chaque action reste
          journalisée et la purge est irréversible.
        </p>
        <label className="field">
          <span>Mot de passe</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "master-error" : undefined}
            required
          />
        </label>
        {error ? (
          <p id="master-error" role="alert" className="alert alert-error">
            {error}
          </p>
        ) : null}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn btn-danger" disabled={pending || !password}>
            {pending ? <span className="spinner" aria-hidden="true" /> : null}
            {pending ? "Vérification…" : "Activer"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Persistent red banner with the countdown and a way out. */
export function MasterModeBanner({
  secondsLeft,
  csrf,
}: {
  secondsLeft: number;
  csrf: string | null;
}) {
  const queryClient = useQueryClient();
  const [leaving, setLeaving] = useState(false);

  async function leave() {
    if (!csrf) return;
    setLeaving(true);
    try {
      await api.disableMasterMode(csrf);
    } finally {
      setLeaving(false);
      await queryClient.invalidateQueries({ queryKey: ["session"] });
    }
  }

  return (
    <div role="status" className="master-banner" data-testid="master-banner">
      <span>
        <strong>Mode maître actif</strong> — purges sans confirmation. Fin dans{" "}
        <span className="num">{clock(secondsLeft)}</span>.
      </span>
      <button
        type="button"
        className="btn btn-small"
        disabled={leaving}
        onClick={() => void leave()}
      >
        {leaving ? "Sortie…" : "Quitter le mode maître"}
      </button>
    </div>
  );
}
