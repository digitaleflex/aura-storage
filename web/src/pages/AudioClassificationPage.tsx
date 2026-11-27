import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AudioClassificationJob } from "../lib/api";
import { makeToast, ToastStack } from "../components/Toasts";
import type { Toast } from "../components/Toasts";

const STATUSES = [
  ["", "Tous"],
  ["queued", "En attente"],
  ["processing", "En cours"],
  ["needs_review", "À valider"],
  ["accepted", "Accepté"],
  ["rejected", "Rejeté"],
  ["failed", "Échec"],
] as const;

function statusLabel(status: string): string {
  return STATUSES.find(([v]) => v === status)?.[1] ?? status;
}

export function AudioClassificationPage() {
  const [jobs, setJobs] = useState<AudioClassificationJob[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [csrf, setCsrf] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  function notify(kind: Toast["kind"], text: string) {
    setToasts((current) => [...current.slice(-3), makeToast(kind, text)]);
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [me, res] = await Promise.all([
        api.me(),
        api.listAudioClassifications({ status: status || undefined, limit: 100 }),
      ]);
      setCsrf(me.csrf_token ?? null);
      setJobs(res.items ?? []);
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { void load(); }, [load]);

  async function review(jobId: string, action: "accept" | "reject") {
    if (!csrf) return;
    setBusyId(jobId);
    try {
      const updated = await api.reviewAudioClassification(jobId, action, csrf);
      setJobs((current) => current.map((j) => (j.id === jobId ? updated : j)));
      notify("ok", action === "accept" ? "Classification acceptée" : "Classification rejetée");
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Action impossible");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="page-shell" style={{ padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 28 }}>Bac à sable audio</h1>
          <p style={{ margin: "4px 0 0", opacity: 0.75 }}>
            Analyse IA des livres audio. Aucune réorganisation automatique : validation humaine requise.
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filtrer par statut">
            {STATUSES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
          <button className="btn btn-ghost" onClick={() => void load()} disabled={loading}>Rafraîchir</button>
        </div>
      </div>

      {loading ? <p>Chargement…</p> : jobs.length === 0 ? (
        <p style={{ opacity: 0.75 }}>Aucun job de classification pour ce filtre.</p>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {jobs.map((job) => (
            <article key={job.id} className="surface-panel" style={{ padding: 16, border: "1px solid var(--border, #333)", borderRadius: 12 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 260 }}>
                  <div style={{ fontWeight: 600 }}>{job.object?.display_name ?? job.object_id}</div>
                  <div style={{ fontSize: 13, opacity: 0.75 }}>
                    {statusLabel(job.status)} · {job.provider ?? "—"} {job.model ?? ""} · confiance {job.confidence != null ? `${Math.round(job.confidence * 100)}%` : "—"}
                  </div>
                  {job.error ? <div style={{ color: "var(--danger, #f66)", fontSize: 13, marginTop: 6 }}>Erreur : {job.error}</div> : null}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn" disabled={!csrf || busyId === job.id || job.status === "accepted"} onClick={() => void review(job.id, "accept")}>Accepter</button>
                  <button className="btn btn-ghost" disabled={!csrf || busyId === job.id || job.status === "rejected"} onClick={() => void review(job.id, "reject")}>Rejeter</button>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8, marginTop: 12, fontSize: 14 }}>
                <div><strong>Catégorie</strong><div>{job.suggested_category ?? "—"}</div></div>
                <div><strong>Thèmes</strong><div>{job.suggested_themes?.join(", ") || "—"}</div></div>
                <div><strong>Langue</strong><div>{job.suggested_language ?? "—"}</div></div>
                <div><strong>Dossier suggéré</strong><div>{job.suggested_folder ?? "—"}</div></div>
              </div>
              {job.reason ? <div style={{ marginTop: 10, fontSize: 14, opacity: 0.9 }}><strong>Raison :</strong> {job.reason}</div> : null}
              {job.transcript_excerpt ? <div style={{ marginTop: 8, fontSize: 13, opacity: 0.75 }}><strong>Extrait :</strong> {job.transcript_excerpt}</div> : null}
            </article>
          ))}
        </div>
      )}
      <ToastStack toasts={toasts} onDismiss={(id) => setToasts((cur) => cur.filter((t) => t.id !== id))} />
    </div>
  );
}
