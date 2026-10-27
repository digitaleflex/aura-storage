import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { ObjectItem } from "../lib/api";
import { describeError } from "../lib/errors";
import { Dialog } from "./Dialog";

function slugify(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

/**
 * Ordered packs: create from the current selection, reorder, publish, and copy
 * the JSON manifest URL consumed by course sites.
 */
export function PacksDialog({
  open,
  csrf,
  selectedIds,
  objects,
  onClose,
  onNotify,
}: {
  open: boolean;
  csrf: string | null;
  selectedIds: Set<string>;
  objects: ObjectItem[];
  onClose: () => void;
  onNotify: (kind: "ok" | "error", text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [order, setOrder] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const packs = useQuery({
    queryKey: ["collections"],
    queryFn: () => api.listCollections(),
    enabled: open,
    retry: false,
  });
  const detail = useQuery({
    queryKey: ["collection", activeId],
    queryFn: () => api.getCollection(activeId!),
    enabled: open && activeId !== null,
    retry: false,
  });

  useEffect(() => {
    if (detail.data) setOrder(detail.data.items.map((i) => i.id));
  }, [detail.data]);

  useEffect(() => {
    if (!open) {
      setTitle("");
      setSlug("");
      setActiveId(null);
      setError(null);
    }
  }, [open]);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["collections"] });
    void queryClient.invalidateQueries({ queryKey: ["collection", activeId] });
  }

  const create = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      return api.createCollection(
        { slug: slug || slugify(title), title: title.trim() },
        csrf,
      );
    },
    onSuccess: (created) => {
      setError(null);
      setTitle("");
      setSlug("");
      setActiveId(created.id);
      refresh();
    },
    onError: (err) => setError(describeError(err, "Création du pack impossible.")),
  });

  const saveItems = useMutation({
    mutationFn: () => {
      if (!csrf || !activeId) throw new Error("Session expirée.");
      return api.setCollectionItems(activeId, order, csrf);
    },
    onSuccess: () => {
      setError(null);
      refresh();
      onNotify("ok", "Ordre du pack enregistré.");
    },
    onError: (err) => setError(describeError(err, "Enregistrement impossible.")),
  });

  const togglePublish = useMutation({
    mutationFn: () => {
      if (!csrf || !activeId) throw new Error("Session expirée.");
      return api.updateCollection(
        activeId, { published: !detail.data?.published }, csrf,
      );
    },
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (err) => setError(describeError(err, "Publication impossible.")),
  });

  const remove = useMutation({
    mutationFn: () => {
      if (!csrf || !activeId) throw new Error("Session expirée.");
      return api.deleteCollection(activeId, csrf);
    },
    onSuccess: () => {
      setActiveId(null);
      refresh();
    },
    onError: (err) => setError(describeError(err, "Suppression impossible.")),
  });

  function move(index: number, delta: number) {
    const next = [...order];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target]!, next[index]!];
    setOrder(next);
  }

  function addSelection() {
    const additions = [...selectedIds].filter((id) => !order.includes(id));
    setOrder([...order, ...additions]);
  }

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const manifest = detail.data?.published
    ? `${origin}/p/${detail.data.slug}.json`
    : "";
  const byId = new Map(objects.map((o) => [o.id, o]));

  return (
    <Dialog open={open} title="Packs de cours" onClose={onClose}>
      <section className="publish-block" aria-labelledby="packs-create">
        <h3 id="packs-create">Créer un pack</h3>
        <form
          className="form form-inline"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label className="field">
            <span>Titre</span>
            <input
              type="text"
              value={title}
              required
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Slug</span>
            <input
              type="text"
              value={slug}
              placeholder={slugify(title) || "maths-l1"}
              onChange={(e) => setSlug(e.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            Créer
          </button>
        </form>
      </section>

      <section className="publish-block" aria-labelledby="packs-list">
        <h3 id="packs-list">Packs existants</h3>
        {packs.isPending ? <p className="muted">Chargement…</p> : null}
        {packs.data && packs.data.items.length === 0 ? (
          <p className="muted">Aucun pack.</p>
        ) : null}
        <ul className="share-list">
          {packs.data?.items.map((pack) => (
            <li key={pack.id} className="share-item">
              <button
                type="button"
                className="link-button"
                onClick={() => setActiveId(pack.id)}
              >
                {pack.title}
              </button>
              <span className="muted">
                {pack.item_count} élément(s) ·{" "}
                {pack.published ? "publié" : "brouillon"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {activeId && detail.data ? (
        <section className="publish-block" aria-labelledby="packs-edit">
          <h3 id="packs-edit">{detail.data.title}</h3>
          <ol className="pack-items">
            {order.map((id, index) => {
              const item = byId.get(id) ?? detail.data?.items.find((i) => i.id === id);
              return (
                <li key={id} className="pack-item">
                  <span>{item?.display_name ?? id}</span>
                  <span className="pack-actions">
                    <button type="button" className="btn btn-small" onClick={() => move(index, -1)}>↑</button>
                    <button type="button" className="btn btn-small" onClick={() => move(index, 1)}>↓</button>
                    <button
                      type="button"
                      className="btn btn-small"
                      onClick={() => setOrder(order.filter((x) => x !== id))}
                    >
                      Retirer
                    </button>
                  </span>
                </li>
              );
            })}
          </ol>
          <div className="dialog-actions">
            <button type="button" className="btn btn-small" onClick={addSelection}>
              Ajouter la sélection ({selectedIds.size})
            </button>
            <button
              type="button"
              className="btn btn-small"
              disabled={saveItems.isPending}
              onClick={() => saveItems.mutate()}
            >
              Enregistrer l'ordre
            </button>
          </div>
          {manifest ? (
            <div className="share-created-row">
              <input
                type="text"
                readOnly
                value={manifest}
                aria-label="Manifest du pack"
                onFocus={(e) => e.currentTarget.select()}
              />
              <button
                type="button"
                className="btn"
                onClick={() =>
                  void navigator.clipboard.writeText(manifest).then(
                    () => onNotify("ok", "Manifest copié."),
                    () => setError("Copie impossible."),
                  )
                }
              >
                Copier
              </button>
            </div>
          ) : null}
          <div className="dialog-actions">
            <button
              type="button"
              className="btn"
              disabled={togglePublish.isPending}
              onClick={() => togglePublish.mutate()}
            >
              {detail.data.published ? "Dépublier" : "Publier le manifest"}
            </button>
            <button
              type="button"
              className="btn btn-danger"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Supprimer le pack
            </button>
          </div>
        </section>
      ) : null}

      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}
