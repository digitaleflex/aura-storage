import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type {
  ObjectItem,
  ObjectShare,
  ShareCreateInput,
  ShareCreateResponse,
} from "../lib/api";
import { describeError } from "../lib/errors";
import {
  SHARE_STATE_LABELS,
  absoluteShareUrl,
  canShareInline,
  shareState,
} from "../lib/shares";
import { Dialog } from "./Dialog";

/** Second-level labels only: the dialog is not the place for a date picker. */
const EXPIRY_OPTIONS = [
  { value: 3_600, label: "1 heure" },
  { value: 86_400, label: "24 heures" },
  { value: 604_800, label: "7 jours" },
  { value: 2_592_000, label: "30 jours" },
];

const MAX_USES_OPTIONS = [
  { value: "", label: "Illimité" },
  { value: "1", label: "1 utilisation" },
  { value: "5", label: "5 utilisations" },
  { value: "25", label: "25 utilisations" },
];

const DATE_FORMAT = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatDate(epoch: number): string {
  return Number.isFinite(epoch) && epoch > 0 ? DATE_FORMAT.format(new Date(epoch * 1000)) : "—";
}

function usesLabel(share: ObjectShare): string {
  const used = `${share.use_count} utilisation${share.use_count > 1 ? "s" : ""}`;
  return share.max_uses === null ? `${used} · illimité` : `${used} / ${share.max_uses}`;
}

/**
 * Create and revoke public share links for one object.
 *
 * The token is returned by the API exactly once, so the freshly minted link is
 * the only chance to copy it: the list below (which only carries the stored
 * fingerprint) can revoke a link but never display it again. Creation and
 * revocation are human-only server-side; the caller only opens this dialog for
 * a human session on an available object.
 */
export function ShareDialog({
  item,
  csrf,
  onClose,
  onNotify,
}: {
  item: ObjectItem | null;
  csrf: string | null;
  onClose: () => void;
  onNotify: (kind: "ok" | "error", text: string) => void;
}) {
  const open = item !== null;
  const queryClient = useQueryClient();
  const [expiresIn, setExpiresIn] = useState("86400");
  const [maxUses, setMaxUses] = useState("");
  const [disposition, setDisposition] = useState<"attachment" | "inline">("attachment");
  const [created, setCreated] = useState<ShareCreateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);

  const sharesQuery = useQuery({
    queryKey: ["object-shares", item?.id],
    queryFn: () => api.listShares(item!.id),
    enabled: open,
    retry: false,
  });

  // Fresh dialog per object: never show one file's link while opening another.
  useEffect(() => {
    setCreated(null);
    setError(null);
    setCopyError(null);
    setConfirmRevokeId(null);
    setDisposition("attachment");
    setExpiresIn("86400");
    setMaxUses("");
  }, [item?.id]);

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["object-shares", item?.id] });
  }

  const createMutation = useMutation({
    mutationFn: (input: ShareCreateInput) => {
      if (!item || !csrf) throw new Error("Session expirée.");
      return api.createShare(item.id, input, csrf);
    },
    onSuccess: (result) => {
      setCreated({
        ...result,
        url: absoluteShareUrl(result.url, window.location.origin),
      });
      setError(null);
      setCopyError(null);
      invalidate();
      onNotify("ok", "Lien de partage créé. Copiez-le maintenant.");
    },
    onError: (err: unknown) => {
      setError(describeError(err, "Création du lien impossible."));
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (shareId: string) => {
      if (!item || !csrf) throw new Error("Session expirée.");
      return api.revokeShare(item.id, shareId, csrf);
    },
    onSuccess: (_result, shareId) => {
      setConfirmRevokeId(null);
      // The one-time link is dead as soon as it is revoked: stop showing it.
      setCreated((current) => (current?.id === shareId ? null : current));
      invalidate();
      onNotify("ok", "Lien révoqué : il ne fonctionne plus.");
    },
    onError: (err: unknown) => {
      setConfirmRevokeId(null);
      setError(describeError(err, "Révocation impossible."));
    },
  });

  async function copyLink() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.url);
      setCopyError(null);
      onNotify("ok", "Lien copié.");
    } catch {
      setCopyError("Copie impossible dans ce navigateur : sélectionnez le lien et copiez-le à la main.");
    }
  }

  const inlineAllowed = canShareInline(item?.content_type);
  const creating = createMutation.isPending;
  const now = Math.floor(Date.now() / 1000);

  return (
    <Dialog open={open} title={item ? `Partager — ${item.display_name}` : "Partager"} onClose={onClose}>
      {created ? (
        <div className="share-created" role="status">
          <strong>Lien créé. Copiez-le maintenant : il ne sera plus affiché.</strong>
          <div className="share-created-row">
            <input
              type="text"
              readOnly
              value={created.url}
              aria-label="Lien de partage"
              onFocus={(e) => e.currentTarget.select()}
            />
            <button type="button" className="btn btn-primary" onClick={() => void copyLink()}>
              Copier
            </button>
          </div>
          <p className="muted">
            Expire le {formatDate(created.expires_at)}
            {created.max_uses === null
              ? " · utilisations illimitées"
              : ` · ${created.max_uses} utilisation${created.max_uses > 1 ? "s" : ""} maximum`}
            .
          </p>
          {copyError ? (
            <p className="alert alert-error" role="alert">
              {copyError}
            </p>
          ) : null}
        </div>
      ) : null}

      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!csrf) {
            setError("Votre session a expiré. Reconnectez-vous.");
            return;
          }
          createMutation.mutate({
            expires_in: Number(expiresIn),
            max_uses: maxUses === "" ? null : Number(maxUses),
            content_disposition: disposition,
          });
        }}
      >
        <div className="share-fields">
          <label className="field">
            <span>Durée</span>
            <select value={expiresIn} onChange={(e) => setExpiresIn(e.target.value)}>
              {EXPIRY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Utilisations maximum</span>
            <select value={maxUses} onChange={(e) => setMaxUses(e.target.value)}>
              {MAX_USES_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>À l'ouverture</span>
            <select
              value={disposition}
              onChange={(e) => setDisposition(e.target.value as "attachment" | "inline")}
            >
              <option value="attachment">Télécharger le fichier</option>
              {inlineAllowed ? (
                <option value="inline">Afficher dans le navigateur</option>
              ) : null}
            </select>
          </label>
        </div>
        <p className="muted share-hint">
          Un lien donne accès à ce fichier sans compte AURA. Révoquez-le dès qu'il
          n'est plus utile.
          {inlineAllowed
            ? ""
            : " Ce type de fichier est partagé en téléchargement uniquement."}
        </p>

        {error ? (
          <p className="alert alert-error" role="alert">
            {error}
          </p>
        ) : null}

        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Fermer
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={creating || !csrf}
          >
            {creating ? "Création…" : "Créer le lien"}
          </button>
        </div>
      </form>

      <section className="share-links" aria-labelledby="share-links-title">
        <h3 id="share-links-title">Liens créés</h3>
        {sharesQuery.isLoading ? (
          <p className="muted" role="status">
            Chargement des liens…
          </p>
        ) : null}
        {sharesQuery.isError ? (
          <p className="alert alert-error" role="alert">
            {describeError(sharesQuery.error, "Liste des liens indisponible.")}
          </p>
        ) : null}
        {sharesQuery.data && sharesQuery.data.items.length === 0 ? (
          <p className="muted">Aucun lien pour ce fichier.</p>
        ) : null}
        {sharesQuery.data && sharesQuery.data.items.length > 0 ? (
          <ul className="share-list">
            {[...sharesQuery.data.items]
              .sort((a, b) => b.created_at - a.created_at)
              .map((share) => {
                const state = shareState(share, now);
                return (
                  <li key={share.id} className="share-item">
                    <div className="share-item-main">
                      <span
                        className={`status ${state === "active" ? "status-ok" : "status-muted"}`}
                      >
                        {SHARE_STATE_LABELS[state]}
                      </span>
                      <span className="muted">
                        {share.content_disposition === "inline" ? "Affichage" : "Téléchargement"}
                        {" · "}
                        {usesLabel(share)}
                        {" · expire le "}
                        {formatDate(share.expires_at)}
                      </span>
                    </div>
                    {state === "active" ? (
                      confirmRevokeId === share.id ? (
                        <div className="share-revoke-confirm">
                          <span>Révoquer ce lien ?</span>
                          <button
                            type="button"
                            className="btn btn-small"
                            onClick={() => setConfirmRevokeId(null)}
                            disabled={revokeMutation.isPending}
                          >
                            Annuler
                          </button>
                          <button
                            type="button"
                            className="btn btn-small btn-danger"
                            onClick={() => revokeMutation.mutate(share.id)}
                            disabled={revokeMutation.isPending}
                          >
                            {revokeMutation.isPending ? "Révocation…" : "Confirmer"}
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-small"
                          onClick={() => setConfirmRevokeId(share.id)}
                        >
                          Révoquer
                        </button>
                      )
                    ) : null}
                  </li>
                );
              })}
          </ul>
        ) : null}
      </section>
    </Dialog>
  );
}
