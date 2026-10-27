import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { ObjectItem } from "../lib/api";
import { describeError } from "../lib/errors";
import { Dialog } from "./Dialog";

/** URL-safe slug from a display name (accents removed, extension dropped). */
export function slugify(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\.[a-z0-9]{1,8}$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

function embedSnippet(item: ObjectItem, url: string): string {
  const type = (item.content_type || "").split(";")[0]?.trim().toLowerCase() ?? "";
  const name = item.display_name.replace(/"/g, "");
  if (type.startsWith("image/")) {
    return `<img src="${url}" alt="${name}" loading="lazy">`;
  }
  if (type.startsWith("video/")) {
    return `<video src="${url}" controls playsinline preload="metadata"></video>`;
  }
  if (type.startsWith("audio/")) {
    return `<audio src="${url}" controls preload="metadata"></audio>`;
  }
  if (type === "application/pdf") {
    return `<iframe src="${url}" title="${name}" sandbox="allow-same-origin allow-popups" referrerpolicy="no-referrer"></iframe>`;
  }
  return `<a href="${url}" rel="noopener">${name}</a>`;
}

/**
 * Publish panel for one object: stable slug, public URL, copyable embed
 * snippet, and content replacement that keeps the URL. The slug is the
 * capability; unpublishing keeps it reserved so the URL can be re-enabled.
 */
export function PublishDialog({
  item,
  objects,
  csrf,
  onClose,
  onChanged,
  onNotify,
}: {
  item: ObjectItem | null;
  objects: ObjectItem[];
  csrf: string | null;
  onClose: () => void;
  onChanged: () => void;
  onNotify: (kind: "ok" | "error", text: string) => void;
}) {
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<"url" | "snippet" | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [confirmReplace, setConfirmReplace] = useState(false);

  useEffect(() => {
    setSlug(item?.public_slug ?? (item ? slugify(item.display_name) : ""));
    setError(null);
    setCopied(null);
    setSourceId("");
    setConfirmReplace(false);
  }, [item?.id, item?.public_slug, item?.display_name]);

  const publish = useMutation({
    mutationFn: (published: boolean) => {
      if (!item || !csrf) throw new Error("Session expirée.");
      return api.setObjectPublication(
        item.id, { slug: slug.trim() || null, published }, csrf,
      );
    },
    onSuccess: (_data, published) => {
      setError(null);
      onNotify("ok", published ? "Objet publié." : "Objet dépublié.");
      onChanged();
    },
    onError: (err) => setError(describeError(err, "Publication impossible.")),
  });

  const replace = useMutation({
    mutationFn: () => {
      if (!item || !csrf) throw new Error("Session expirée.");
      if (!sourceId) throw new Error("Choisissez le fichier de remplacement.");
      return api.replaceObjectContent(item.id, sourceId, csrf);
    },
    onSuccess: () => {
      setError(null);
      setConfirmReplace(false);
      setSourceId("");
      onNotify("ok", "Contenu remplacé : l'URL publique est inchangée.");
      onChanged();
    },
    onError: (err) =>
      setError(describeError(err, "Remplacement impossible.")),
  });

  const open = item !== null;
  const published = Boolean(item?.published_at && item?.public_slug);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const publicUrl = published ? `${origin}/m/${item?.public_slug}` : "";
  const snippet = item && published ? embedSnippet(item, publicUrl) : "";
  const candidates = objects.filter(
    (o) => o.id !== item?.id && o.status === "available" && !o.public_slug,
  );

  async function copy(kind: "url" | "snippet") {
    try {
      await navigator.clipboard.writeText(kind === "url" ? publicUrl : snippet);
      setCopied(kind);
      onNotify("ok", kind === "url" ? "URL copiée." : "Snippet copié.");
    } catch {
      setError("Copie impossible dans ce navigateur.");
    }
  }

  return (
    <Dialog
      open={open}
      title={item ? `Publier — ${item.display_name}` : "Publier"}
      onClose={onClose}
    >
      {item ? (
        <>
          <form
            className="form"
            onSubmit={(e) => {
              e.preventDefault();
              publish.mutate(true);
            }}
          >
            <label className="field">
              <span>Slug public (2–63 caractères, minuscules, chiffres, tirets)</span>
              <input
                type="text"
                value={slug}
                maxLength={63}
                required
                onChange={(e) => setSlug(e.target.value)}
                placeholder="maths-l1-introduction"
              />
            </label>
            <p className="muted share-hint">
              URL permanente :{" "}
              <span className="mono">{slug ? `${origin}/m/${slug}` : "—"}</span>
              . Elle survit au remplacement du contenu ; dépublier la réserve
              sans la libérer.
            </p>
            <div className="dialog-actions">
              <button type="button" className="btn" onClick={onClose}>
                Fermer
              </button>
              {published ? (
                <button
                  type="button"
                  className="btn"
                  disabled={publish.isPending}
                  onClick={() => publish.mutate(false)}
                >
                  Dépublier
                </button>
              ) : null}
              <button
                type="submit"
                className="btn btn-primary"
                disabled={publish.isPending || !csrf || slug.trim().length < 2}
              >
                {publish.isPending
                  ? "Enregistrement…"
                  : published
                    ? "Mettre à jour"
                    : "Publier"}
              </button>
            </div>
          </form>

          {published ? (
            <section className="publish-block" aria-labelledby="publish-link-title">
              <h3 id="publish-link-title">URL et intégration</h3>
              <div className="share-created-row">
                <input
                  type="text"
                  readOnly
                  value={publicUrl}
                  aria-label="URL publique"
                  onFocus={(e) => e.currentTarget.select()}
                />
                <button type="button" className="btn" onClick={() => void copy("url")}>
                  {copied === "url" ? "Copiée" : "Copier"}
                </button>
              </div>
              <label className="field">
                <span>Snippet à coller dans le site</span>
                <textarea
                  readOnly
                  rows={3}
                  value={snippet}
                  onFocus={(e) => e.currentTarget.select()}
                />
              </label>
              <button type="button" className="btn btn-small" onClick={() => void copy("snippet")}>
                {copied === "snippet" ? "Snippet copié" : "Copier le snippet"}
              </button>
            </section>
          ) : null}

          {published ? (
            <section className="publish-block" aria-labelledby="publish-replace-title">
              <h3 id="publish-replace-title">Remplacer le contenu (même URL)</h3>
              <p className="muted">
                Importez d'abord la nouvelle version dans Fichiers, puis
                sélectionnez-la ici. Le fichier cible garde son URL, son nom et
                son dossier ; l'ancien contenu et la source sont supprimés.
              </p>
              <label className="field">
                <span>Nouveau contenu</span>
                <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
                  <option value="">— choisir un fichier disponible —</option>
                  {candidates.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.display_name} ({candidate.content_type})
                    </option>
                  ))}
                </select>
              </label>
              <div className="dialog-actions">
                {confirmReplace ? (
                  <>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setConfirmReplace(false)}
                      disabled={replace.isPending}
                    >
                      Annuler
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => replace.mutate()}
                      disabled={replace.isPending}
                    >
                      {replace.isPending ? "Remplacement…" : "Confirmer le remplacement"}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn"
                    disabled={!sourceId}
                    onClick={() => setConfirmReplace(true)}
                  >
                    Remplacer le contenu
                  </button>
                )}
              </div>
            </section>
          ) : null}

          {error ? (
            <p className="alert alert-error" role="alert">
              {error}
            </p>
          ) : null}
        </>
      ) : null}
    </Dialog>
  );
}
