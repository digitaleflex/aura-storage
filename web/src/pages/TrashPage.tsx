import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useAuth } from "../lib/auth";
import {
  api,
  type ObjectItem,
} from "../lib/api";
import { describeError } from "../lib/errors";
import { VaultMark } from "../components/VaultMark";
import { ToastStack, makeToast, type Toast } from "../components/Toasts";
import { EmptyState } from "../components/EmptyState";

export function TrashPage() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [objects, setObjects] = useState<ObjectItem[]>([]);
  const [csrf, setCsrf] = useState<string | null>(null);
  const [processing, setProcessing] = useState<Set<string>>(new Set());

  function notify(kind: Toast["kind"], text: string) {
    setToasts((current) => [...current.slice(-3), makeToast(kind, text)]);
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const me = await api.me();
        setCsrf(me.csrf_token ?? null);

        const resp = await api.listObjects({ status: "deleted" });
        if (!cancelled) {
          setObjects(resp.items);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(describeError(err, "Impossible de charger la corbeille."));
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="trash-page" data-testid="trash-page">
        <div className="trash-shell">
          <VaultMark />
          <div className="trash-header">
            <h1>Corbeille</h1>
            <p className="trash-subtitle muted">Chargement des objets supprimés…</p>
          </div>
          <p className="muted" role="status" aria-live="polite">
            Chargement de la corbeille…
          </p>
        </div>
      </div>
    );
  }

  const isPurging = (id: string) => processing.has(id);

  async function handleRestore(id: string) {
    if (!csrf) return;
    setProcessing((current) => new Set([...current, id]));
    try {
      await api.restoreObject(id, csrf);
      notify("ok", "Objet restauré.");
      setObjects((current) => current.filter((o) => o.id !== id));
    } catch (err) {
      notify("error", describeError(err, "Restauration impossible."));
    } finally {
      setProcessing((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }

  async function handlePurge(id: string) {
    if (!csrf) return;
    setProcessing((current) => new Set([...current, id]));
    try {
      await api.purgeObject(id, csrf);
      notify("ok", "Objet purgé définitivement.");
      setObjects((current) => current.filter((o) => o.id !== id));
    } catch (err) {
      notify("error", describeError(err, "Purge impossible."));
    } finally {
      setProcessing((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }

  if (objects.length === 0) {
    return (
      <div className="trash-page" data-testid="trash-page">
        <ToastStack toasts={toasts} onDismiss={(id: number) =>
          setToasts((current) => current.filter((t) => t.id !== id))
        } />
        <div className="trash-shell">
          <VaultMark />
          <div className="trash-header">
            <h1>Corbeille</h1>
            <p className="trash-subtitle">
              Vos objets supprim&eacute;s sont conserv&eacute;s temporairement.
            </p>
          </div>
          <div aria-live="polite">
            <EmptyState
              className="trash-empty"
              icon="🗑️"
              title="Corbeille vide"
              description="Aucun objet supprimé à restaurer ou purger."
            />
          </div>
          <div className="trash-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => navigate({ to: "/" })}
            >
              Aller aux fichiers
            </button>
            <button
              type="button"
              className="btn btn-small btn-ghost"
              aria-label="Se déconnecter d'AURA Vault"
              onClick={() => {
                void logout();
                navigate({ to: "/login" });
              }}
            >
              Déconnexion
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="trash-page" data-testid="trash-page">
      <ToastStack toasts={toasts} onDismiss={(id: number) =>
        setToasts((current) => current.filter((t) => t.id !== id))
      } />
      <div className="trash-shell">
        <VaultMark />
        <div className="trash-header">
          <h1>Corbeille</h1>
          <p className="trash-subtitle">
            {objects.length} objet{objects.length > 1 ? "s" : ""} supprim&eacute;&hellip;
          </p>
        </div>

        {error && (
          <div className="alert alert-error trash-error" role="alert">
            <span>{error}</span>
            <button
              type="button"
              className="btn btn-small"
              onClick={() => window.location.reload()}
            >
              Rafraîchir
            </button>
          </div>
        )}

        <table aria-label="Objets dans la corbeille">
          <thead>
            <tr>
              <th scope="col">Objet</th>
              <th scope="col">Type</th>
              <th scope="col">Taille</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {objects.map((obj) => (
              <tr key={obj.id}>
                <td>{obj.display_name}</td>
                <td>{obj.content_type}</td>
                <td>{formatBytes(obj.size_bytes)}</td>
                <td className="trash-row-actions">
                  <button
                    type="button"
                    className="btn btn-small"
                    disabled={isPurging(obj.id)}
                    aria-label={`Restaurer ${obj.display_name}`}
                    onClick={() => void handleRestore(obj.id)}
                  >
                    Restaurer
                  </button>
                  <button
                    type="button"
                    className="btn btn-small btn-danger"
                    disabled={isPurging(obj.id)}
                    aria-label={`Purger définitivement ${obj.display_name}`}
                    onClick={() => void handlePurge(obj.id)}
                  >
                    Purger
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="trash-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate({ to: "/" })}
          >
            Aller aux fichiers
          </button>
          <button
            type="button"
            className="btn btn-small btn-ghost"
            aria-label="Se déconnecter d'AURA Vault"
            onClick={() => {
              void logout();
              navigate({ to: "/login" });
            }}
          >
            Déconnexion
          </button>
        </div>
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 o";
  const k = 1024;
  const sizes = ["o", "Ko", "Mo", "Go", "To"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}
