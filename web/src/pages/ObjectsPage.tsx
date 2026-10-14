import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, putToPresignedUrl } from "../lib/api";
import type { ObjectItem } from "../lib/api";

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) {
    return "unknown size";
  }
  if (size === 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  const value = size / 1024 ** index;
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function ObjectsPage() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const objectsQuery = useQuery({
    queryKey: ["objects"],
    queryFn: () => api.listObjects(),
  });

  const uploadMutation = useMutation({
    mutationFn: async (selected: File) => {
      // Step 1: ask the API for a short-lived upload intent.
      const intent = await api.createUploadIntent({
        bucket: "aura",
        display_name: selected.name,
        content_type: selected.type || "application/octet-stream",
      });
      // Step 2: PUT the bytes directly to the presigned URL.
      await putToPresignedUrl(intent.upload_url, selected);
      // Step 3: commit so the catalogue marks the object available.
      return api.commitObject(intent.id);
    },
    onSuccess: () => {
      setFile(null);
      setUploadError(null);
      void queryClient.invalidateQueries({ queryKey: ["objects"] });
    },
    onError: (err: unknown) => {
      setUploadError(err instanceof Error ? err.message : "Upload failed.");
    },
  });

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    setUploadError(null);
    if (!file) {
      setUploadError("Select a file first.");
      return;
    }
    uploadMutation.mutate(file);
  }

  async function handleDownload(item: ObjectItem) {
    setDownloadError(null);
    try {
      const intent = await api.createDownloadIntent(item.id);
      window.open(intent.download_url, "_blank", "noopener");
    } catch (err) {
      setDownloadError(
        err instanceof ApiError ? `Download refused: ${err.detail}` : "Download failed.",
      );
    }
  }

  const items = objectsQuery.data?.items ?? [];

  return (
    <div className="stack">
      <section className="card">
        <h1>Objects</h1>
        {objectsQuery.isPending ? (
          <p className="muted">Loading catalogue…</p>
        ) : objectsQuery.isError ? (
          <p role="alert" className="alert alert-error">
            Catalogue unavailable. No cached data is shown as current.
          </p>
        ) : items.length === 0 ? (
          <p className="empty">No objects yet — the catalogue is empty.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Size</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.display_name}</td>
                  <td className="muted">{item.content_type}</td>
                  <td>{formatBytes(item.size_bytes)}</td>
                  <td>{item.status}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-small"
                      disabled={item.status !== "available"}
                      onClick={() => void handleDownload(item)}
                    >
                      Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {downloadError ? (
          <p role="alert" className="alert alert-error">{downloadError}</p>
        ) : null}
      </section>

      <section className="card">
        <h2>Upload</h2>
        <p className="muted">
          Three steps: upload intent → direct PUT to the short-lived URL → commit.
        </p>
        <form onSubmit={(e) => void handleUpload(e)} className="form form-inline">
          <label className="field">
            <span>File</span>
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
            {uploadMutation.isPending ? "Uploading…" : "Upload and commit"}
          </button>
        </form>
        {uploadError ? (
          <p role="alert" className="alert alert-error">{uploadError}</p>
        ) : null}
        {uploadMutation.isSuccess ? (
          <p role="status" className="alert alert-ok">Upload committed.</p>
        ) : null}
      </section>
    </div>
  );
}
