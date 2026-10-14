import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, putToPresignedUrl } from "../lib/api";
import type { ObjectItem } from "../lib/api";
import { useAuth } from "../lib/auth";

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) {
    return "taille inconnue";
  }
  if (size === 0) {
    return "0 o";
  }
  const units = ["o", "Ko", "Mo", "Go", "To"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  const value = size / 1024 ** index;
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function statusChip(status: string) {
  if (status === "available") {
    return <span className="chip chip-ok">Disponible</span>;
  }
  if (status === "pending") {
    return <span className="chip chip-warn">En cours</span>;
  }
  return <span className="chip chip-muted">{status}</span>;
}

export function ObjectsPage() {
  const { csrf } = useAuth();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [filter, setFilter] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const objectsQuery = useQuery({
    queryKey: ["objects"],
    queryFn: () => api.listObjects(),
  });

  const uploadMutation = useMutation({
    mutationFn: async (selected: File) => {
      if (!csrf) {
        throw new Error("Session expirée. Reconnectez-vous.");
      }
      // Étape 1 : demander une intention d'envoi de courte durée.
      const intent = await api.createUploadIntent(
        {
          bucket: "aura",
          display_name: selected.name,
          content_type: selected.type || "application/octet-stream",
        },
        csrf,
      );
      // Étape 2 : envoyer les octets directement vers l'URL présignée.
      await putToPresignedUrl(intent.upload_url, selected);
      // Étape 3 : valider pour que le catalogue marque l'objet disponible.
      return api.commitObject(intent.id, csrf);
    },
    onSuccess: () => {
      setFile(null);
      setUploadError(null);
      void queryClient.invalidateQueries({ queryKey: ["objects"] });
    },
    onError: (err: unknown) => {
      setUploadError(err instanceof Error ? err.message : "Envoi impossible.");
    },
  });

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    setUploadError(null);
    if (!file) {
      setUploadError("Choisissez d'abord un fichier.");
      return;
    }
    uploadMutation.mutate(file);
  }

  async function handleDownload(item: ObjectItem) {
    setDownloadError(null);
    if (!csrf) {
      setDownloadError("Session expirée. Reconnectez-vous.");
      return;
    }
    try {
      const intent = await api.createDownloadIntent(item.id, csrf);
      window.open(intent.download_url, "_blank", "noopener");
    } catch (err) {
      setDownloadError(
        err instanceof ApiError
          ? `Téléchargement refusé : ${err.detail}`
          : "Téléchargement impossible.",
      );
    }
  }

  const items = objectsQuery.data?.items ?? [];
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? items.filter((item) => item.display_name.toLowerCase().includes(needle))
    : items;

  return (
    <div className="stack">
      <h1>Fichiers</h1>
      <p className="muted">
        {items.length === 0
          ? "Votre coffre est vide."
          : `${items.length} objet${items.length > 1 ? "s" : ""} chiffré${items.length > 1 ? "s" : ""} au repos.`}
      </p>

      <div className="search">
        <label className="field">
          <span className="visually-hidden">Rechercher un fichier</span>
          <input
            type="text"
            name="filter"
            placeholder="Rechercher par nom…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </label>
      </div>

      {objectsQuery.isPending ? (
        <p className="muted">Chargement du catalogue…</p>
      ) : objectsQuery.isError ? (
        <p role="alert" className="alert alert-error">
          Catalogue indisponible. Aucune donnée en cache n'est présentée comme actuelle.
        </p>
      ) : visible.length === 0 ? (
        <p className="empty">
          {needle
            ? "Aucun fichier ne correspond à cette recherche."
            : "Aucun fichier pour l'instant — importez votre premier objet ci-dessous."}
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Nom</th>
                <th scope="col">Type</th>
                <th scope="col">Taille</th>
                <th scope="col">État</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => (
                <tr key={item.id}>
                  <td className="name">{item.display_name}</td>
                  <td className="muted">{item.content_type}</td>
                  <td className="num">{formatBytes(item.size_bytes)}</td>
                  <td>{statusChip(item.status)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-small"
                      disabled={item.status !== "available"}
                      onClick={() => void handleDownload(item)}
                    >
                      Télécharger
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {downloadError ? (
        <p role="alert" className="alert alert-error">
          {downloadError}
        </p>
      ) : null}

      <section className="card" aria-labelledby="upload-title">
        <h2 id="upload-title">Importer</h2>
        <p className="muted">
          Intention d'envoi → dépôt direct vers l'URL à courte durée → validation
          avec contrôle d'intégrité.
        </p>
        <form onSubmit={(e) => void handleUpload(e)} className="form form-inline">
          <label className="field">
            <span>Fichier</span>
            <input
              type="file"
              name="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={uploadMutation.isPending}
          >
            {uploadMutation.isPending ? "Envoi…" : "Importer et valider"}
          </button>
        </form>
        {uploadError ? (
          <p role="alert" className="alert alert-error">
            {uploadError}
          </p>
        ) : null}
        {uploadMutation.isSuccess ? (
          <p role="status" className="alert alert-ok">
            Import validé et vérifié.
          </p>
        ) : null}
      </section>
    </div>
  );
}
