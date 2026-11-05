import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useAuth, useSession } from "../lib/auth";
import { api, type ObjectItem, type FolderItem } from "../lib/api";
import { describeError } from "../lib/errors";
import { VaultMark } from "../components/VaultMark";
import { ShareDialog, type ShareTarget } from "../components/ShareDialog";
import { ToastStack, makeToast, type Toast } from "../components/Toasts";

interface ShareEntry {
  kind: "object" | "folder";
  id: string;
  name: string;
}

export function SharesPage() {
  const { logout } = useAuth();
  const session = useSession();
  const navigate = useNavigate();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [objects, setObjects] = useState<ObjectItem[]>([]);
  const [folders, setFolders] = useState<FolderItem[]>([]);
  const [openShare, setOpenShare] = useState<ShareTarget | null>(null);
  const [csrf, setCsrf] = useState<string | null>(null);

  function notify(kind: Toast["kind"], text: string) {
    setToasts((current) => [...current.slice(-3), makeToast(kind, text)]);
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const me = await api.me();
        setCsrf(me.csrf_token ?? null);

        const [objResp, folderResp] = await Promise.all([
          api.listObjects({}),
          api.listAllFolders(),
        ]);
        if (!cancelled) {
          setObjects(objResp.items);
          setFolders(folderResp.items);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(describeError(err, "Impossible de charger les partages."));
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
      <div className="shares-page" data-testid="shares-page">
        <VaultMark />
        <p>Chargement des partages&hellip;</p>
      </div>
    );
  }

  const allEntries = useMemo<ShareEntry[]>(() => {
    const entries: ShareEntry[] = [];
    for (const o of objects) {
      entries.push({ kind: "object", id: o.id, name: o.display_name });
    }
    for (const f of folders) {
      entries.push({ kind: "folder", id: f.id, name: f.name });
    }
    return entries.sort((a, b) => a.name.localeCompare(b.name));
  }, [objects, folders]);

  return (
    <div className="shares-page" data-testid="shares-page">
      <ToastStack toasts={toasts} onDismiss={(id: number) =>
        setToasts((current) => current.filter((t) => t.id !== id))
      } />
      <div className="shares-shell">
        <VaultMark />
        <div className="shares-header">
          <h1>Partages publics</h1>
          <p className="shares-subtitle">
            G&eacute;rez les liens publics de {session.data?.name ?? "vous"}
          </p>
        </div>

        {error && (
          <div className="shares-error" role="alert">
            {error}
            <button
              type="button"
              className="btn btn-small"
              onClick={() => window.location.reload()}
            >
              Rafra&icirc;chir
            </button>
          </div>
        )}

        {allEntries.length === 0 ? (
          <section className="shares-empty">
            <span className="shares-empty-icon" aria-hidden="true">
              📂
            </span>
            <h2>Aucun fichier ni dossier</h2>
            <p>
              Vous n'avez aucun objet à partager. Importez des fichiers depuis la
              page Fichiers, puis revenez ici pour cr&eacute;er des liens publics.
            </p>
          </section>
        ) : null}

        {allEntries.length > 0 ? (
          <section className="shares-list" aria-label="Ressources partageables">
            <h2>Ressources ({allEntries.length})</h2>
            <table aria-label="Liste des ressources">
              <thead>
                <tr>
                  <th>Ressource</th>
                  <th>Type</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {allEntries.map((entry) => (
                  <tr key={entry.id}>
                    <td>{entry.name}</td>
                    <td>
                      {entry.kind === "object" ? "Fichier" : "Dossier"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-small"
                        onClick={() => {
                          const target: ShareTarget =
                            entry.kind === "object"
                              ? {
                                  kind: "object",
                                  item: objects.find((o) => o.id === entry.id)!,
                                }
                              : {
                                  kind: "folder",
                                  folder: folders.find((f) => f.id === entry.id)!,
                                };
                          setOpenShare(target);
                        }}
                      >
                        Partager / G&eacute;rer
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}

        <div className="shares-actions">
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
            onClick={() => {
              void logout();
              navigate({ to: "/login" });
            }}
          >
            D&eacute;connexion
          </button>
        </div>
      </div>

      <ShareDialog
        target={openShare}
        csrf={csrf}
        onClose={() => setOpenShare(null)}
        onNotify={notify}
      />
    </div>
  );
}
