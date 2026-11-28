import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import type { AudioClassificationJob } from "../lib/api";
import { useTransfers } from "../lib/transferContext";
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

function fmtBytes(n?: number | null): string {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let v = n, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function AudioClassificationPage() {
  const [jobs, setJobs] = useState<AudioClassificationJob[]>([]);
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [minConfidence, setMinConfidence] = useState("");
  const [loading, setLoading] = useState(true);
  const [csrf, setCsrf] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [enqueuing, setEnqueuing] = useState(false);
  const [edits, setEdits] = useState<Record<string, { category: string; themes: string; folder: string }>>({});
  const [feedback, setFeedback] = useState<any>(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const transfers = useTransfers();
  const enqueuedObjectIds = useRef<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  function notify(kind: Toast["kind"], text: string) {
    setToasts((current) => [...current.slice(-3), makeToast(kind, text)]);
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [me, res] = await Promise.all([
        api.me(),
        api.listAudioClassifications({ status: status || undefined, limit: 200 }),
      ]);
      setCsrf(me.csrf_token ?? null);
      const items = res.items ?? [];
      setJobs(items);
      setSelected({});
      setEdits((prev) => {
        const next = { ...prev };
        for (const j of items) {
          if (!next[j.id]) {
            next[j.id] = {
              category: j.suggested_category ?? "",
              themes: (j.suggested_themes ?? []).join(", "),
              folder: j.suggested_folder ?? "",
            };
          }
        }
        return next;
      });
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { void load(); }, [load]);

  // Auto-enqueue classification for newly uploaded audio files.
  useEffect(() => {
    if (!csrf) return;
    const ready = transfers.queue.items.filter(
      (it) => it.state.phase === "available" && it.state.intentId && !enqueuedObjectIds.current.has(it.state.intentId)
    );
    const audio = ready.filter((it) => /\.(mp3|m4a|mp4|wav|ogg|flac|aac|opus)$/i.test(it.state.fileName || ""));
    if (audio.length === 0) return;
    for (const it of audio) enqueuedObjectIds.current.add(it.state.intentId!);
    void (async () => {
      try {
        const ids = audio.map((it) => it.state.intentId!).filter(Boolean);
        const res = await api.enqueueAudioClassifications(ids, csrf);
        const n = res.enqueued?.length ?? 0;
        if (n > 0) notify("ok", `${n} fichier(s) audio envoyé(s) à l'analyse`);
        if ((res.skipped?.length ?? 0) > 0) notify("info", `${res.skipped.length} fichier(s) ignoré(s) (non audio ou déjà en file)`);
        await load();
      } catch (e) {
        notify("error", e instanceof Error ? e.message : "Enqueue automatique impossible");
      }
    })();
  }, [transfers.queue.items, csrf, load]);

  const filtered = useMemo(() => {
    return jobs.filter((j) => {
      if (category && (j.suggested_category || "") !== category) return false;
      if (minConfidence) {
        const c = j.confidence ?? -1;
        if (c < Number(minConfidence)) return false;
      }
      return true;
    });
  }, [jobs, category, minConfidence]);

  const categories = useMemo(() => {
    const s = new Set<string>();
    for (const j of jobs) if (j.suggested_category) s.add(j.suggested_category);
    return Array.from(s).sort();
  }, [jobs]);

  async function review(jobId: string, action: "accept" | "reject") {
    if (!csrf) return;
    setBusyId(jobId);
    try {
      const e = edits[jobId];
      const correction = e ? {
        corrected_category: e.category.trim() || undefined,
        corrected_themes: e.themes.split(",").map((t) => t.trim()).filter(Boolean),
        corrected_folder: e.folder.trim() || undefined,
      } : undefined;
      const updated = await api.reviewAudioClassification(jobId, action, csrf, correction);
      setJobs((current) => current.map((j) => (j.id === jobId ? { ...j, ...updated } : j)));
      const tagMsg = action === "accept" && updated.applied_tags === false ? " (tags non appliqués: confiance < 80% ou correction)" : "";
      notify("ok", (action === "accept" ? "Classification acceptée" : "Classification rejetée") + tagMsg);
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Action impossible");
    } finally {
      setBusyId(null);
    }
  }

  async function bulkReview(action: "accept" | "reject") {
    if (!csrf) return;
    const ids = filtered.filter((j) => selected[j.id]).map((j) => j.id);
    if (ids.length === 0) return;
    setBusyId("bulk");
    let ok = 0, err = 0;
    for (const id of ids) {
      try {
        const e = edits[id];
        const correction = e ? {
          corrected_category: e.category.trim() || undefined,
          corrected_themes: e.themes.split(",").map((t) => t.trim()).filter(Boolean),
          corrected_folder: e.folder.trim() || undefined,
        } : undefined;
        const updated = await api.reviewAudioClassification(id, action, csrf, correction);
        setJobs((current) => current.map((j) => (j.id === id ? { ...j, ...updated } : j)));
        ok++;
      } catch { err++; }
    }
    setBusyId(null);
    setSelected({});
    notify(err ? "info" : "ok", `Lot ${action === "accept" ? "accepté" : "rejeté"}: ${ok} ok${err ? `, ${err} erreur(s)` : ""}`);
  }

  async function enqueueUnclassified() {
    if (!csrf) return;
    setEnqueuing(true);
    try {
      const res = await api.enqueueUnclassifiedAudioClassifications(200, csrf);
      notify("ok", `${res.count} audio(s) envoyé(s) à l'analyse`);
      await load();
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Enqueue impossible");
    } finally {
      setEnqueuing(false);
    }
  }

  function onPickFiles(files: FileList | null) {
    if (!csrf || !files || files.length === 0) return;
    const entries = Array.from(files).map((file) => ({ file }));
    transfers.start(entries, { csrf, folderId: null });
    notify("info", `${entries.length} fichier(s) en cours d'upload. L'analyse sera lancée automatiquement à la fin.`);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function loadFeedback() {
    try {
      const f = await api.getAudioClassificationFeedback(500);
      setFeedback(f);
      setShowFeedback(true);
    } catch (e) {
      notify("error", e instanceof Error ? e.message : "Feedback impossible");
    }
  }

  function exportFeedback(format: "json" | "csv") {
    if (!feedback) return;
    const rows = [...(feedback.rejected || []), ...(feedback.low_confidence || [])];
    if (format === "json") {
      const blob = new Blob([JSON.stringify({ ...feedback, exported_rows: rows }, null, 2)], { type: "application/json" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "audio-classification-feedback.json"; a.click();
      return;
    }
    const keys = ["id","object_id","display_name","status","suggested_category","confidence","provider","reason"];
    const esc = (v: any) => `"${String(v ?? "").replace(/"/g,'""')}"`;
    const csv = [keys.join(","), ...rows.map((r:any) => keys.map((k)=>esc(r[k])).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "audio-classification-feedback.csv"; a.click();
  }

  const allSelected = filtered.length > 0 && filtered.every((j) => selected[j.id]);

  return (
    <div className="page-shell" style={{ padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 28 }}>Bac à sable audio</h1>
          <p style={{ margin: "4px 0 0", opacity: 0.75 }}>
            Analyse IA des livres audio. Aucune réorganisation automatique : validation humaine requise.
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*,.mp3,.m4a,.wav,.ogg,.flac,.aac,.opus"
            multiple
            style={{ display: "none" }}
            onChange={(e) => onPickFiles(e.target.files)}
          />
          <button className="btn" onClick={() => fileInputRef.current?.click()} disabled={!csrf}>
            Uploader des livres audio
          </button>
          <button className="btn btn-ghost" onClick={() => void enqueueUnclassified()} disabled={!csrf || enqueuing}>
            {enqueuing ? "Envoi…" : "Analyser les audios non classés"}
          </button>
          <button className="btn btn-ghost" onClick={() => void loadFeedback()}>Feedback/erreurs</button>
          <button className="btn btn-ghost" onClick={() => void load()} disabled={loading}>Rafraîchir</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filtrer par statut">
          {STATUSES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Filtrer par catégorie">
          <option value="">Toutes catégories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={minConfidence} onChange={(e) => setMinConfidence(e.target.value)} aria-label="Confiance minimum">
          <option value="">Toute confiance</option>
          <option value="0.8">≥ 80%</option>
          <option value="0.6">≥ 60%</option>
          <option value="0.4">≥ 40%</option>
        </select>
        <label style={{ fontSize: 13, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={allSelected} onChange={(e) => {
            const v = e.target.checked;
            setSelected(Object.fromEntries(filtered.map((j) => [j.id, v])));
          }} />
          Tout sélectionner
        </label>
        <button className="btn btn-ghost" disabled={!csrf || busyId === "bulk" || !Object.values(selected).some(Boolean)} onClick={() => void bulkReview("accept")}>Accepter sélection</button>
        <button className="btn btn-ghost" disabled={!csrf || busyId === "bulk" || !Object.values(selected).some(Boolean)} onClick={() => void bulkReview("reject")}>Rejeter sélection</button>
      </div>

      {showFeedback && feedback ? (
        <div className="surface-panel" style={{ padding: 16, border: "1px solid var(--border, #333)", borderRadius: 12, marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <strong>Feedback / erreurs</strong>
            <span style={{ opacity: 0.7 }}>total {feedback.total}</span>
            <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              <button className="btn btn-ghost" onClick={() => exportFeedback("csv")}>Export CSV</button>
              <button className="btn btn-ghost" onClick={() => exportFeedback("json")}>Export JSON</button>
              <button className="btn btn-ghost" onClick={() => setShowFeedback(false)}>Fermer</button>
            </div>
          </div>
          <div style={{ fontSize: 13, opacity: 0.8, marginTop: 8 }}>
            Statuts: {Object.entries(feedback.by_status || {}).map(([k,v]) => `${k}:${v}`).join(" · ")}
          </div>
          <div style={{ fontSize: 13, opacity: 0.8, marginTop: 4 }}>
            Catégories: {Object.entries(feedback.by_category || {}).map(([k,v]) => `${k}:${v}`).join(" · ")}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12, marginTop: 12 }}>
            <div>
              <strong>Rejetés ({(feedback.rejected || []).length})</strong>
              <div style={{ maxHeight: 180, overflow: "auto", fontSize: 12 }}>
                {(feedback.rejected || []).slice(0,20).map((r:any) => <div key={r.id}>{r.display_name || r.object_id} — {r.suggested_category} ({Math.round((r.confidence||0)*100)}%)</div>)}
              </div>
            </div>
            <div>
              <strong>Faible confiance ({(feedback.low_confidence || []).length})</strong>
              <div style={{ maxHeight: 180, overflow: "auto", fontSize: 12 }}>
                {(feedback.low_confidence || []).slice(0,20).map((r:any) => <div key={r.id}>{r.display_name || r.object_id} — {r.suggested_category} ({Math.round((r.confidence||0)*100)}%)</div>)}
              </div>
            </div>
          </div>
          {feedback.hint ? <div style={{ marginTop: 8, fontSize: 12, opacity: 0.75 }}>{feedback.hint}</div> : null}
        </div>
      ) : null}

      {loading ? <p>Chargement…</p> : filtered.length === 0 ? (
        <p style={{ opacity: 0.75 }}>Aucun job de classification pour ces filtres.</p>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {filtered.map((job) => {
            const q = job.quality as Record<string, unknown> | null;
            const conf = job.confidence ?? 0;
            const lowConf = conf < 0.8;
            return (
              <article key={job.id} className="surface-panel" style={{ padding: 16, border: "1px solid var(--border, #333)", borderRadius: 12 }}>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
                  <input type="checkbox" checked={!!selected[job.id]} onChange={(e) => setSelected((s) => ({ ...s, [job.id]: e.target.checked }))} aria-label={`Sélectionner ${job.object?.display_name ?? job.id}`} />
                  <div style={{ flex: 1, minWidth: 260 }}>
                    <div style={{ fontWeight: 600 }}>{job.object?.display_name ?? job.object_id}</div>
                    <div style={{ fontSize: 13, opacity: 0.75 }}>
                      {statusLabel(job.status)} · {job.provider ?? "—"} {job.model ?? ""} · confiance {job.confidence != null ? `${Math.round(job.confidence * 100)}%` : "—"}
                      {lowConf && job.status === "needs_review" ? <span style={{ color: "var(--warning, #f90)", marginLeft: 8 }}>⚠ &lt; 80%: tags non appliqués à l’acceptation</span> : null}
                      {(() => { const e = edits[job.id]; const changed = e && (e.category !== (job.suggested_category ?? "") || e.themes !== (job.suggested_themes ?? []).join(", ") || e.folder !== (job.suggested_folder ?? "")); return changed ? <span style={{ marginLeft: 8, color: "var(--accent, #4af)" }}>✎ corrigé</span> : null; })()}
                    </div>
                    {job.error ? <div style={{ color: "var(--danger, #f66)", fontSize: 13, marginTop: 6 }}>Erreur : {job.error}</div> : null}
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn" disabled={!csrf || busyId === job.id || job.status === "accepted"} onClick={() => void review(job.id, "accept")}>Accepter</button>
                    <button className="btn btn-ghost" disabled={!csrf || busyId === job.id || job.status === "rejected"} onClick={() => void review(job.id, "reject")}>Rejeter</button>
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8, marginTop: 12, fontSize: 14 }}>
                  <label><strong>Catégorie</strong>
                    <input value={edits[job.id]?.category ?? job.suggested_category ?? ""} onChange={(ev) => setEdits((s) => ({ ...s, [job.id]: { ...(s[job.id] ?? { category: job.suggested_category ?? "", themes: (job.suggested_themes ?? []).join(", "), folder: job.suggested_folder ?? "" }), category: ev.target.value } }))} style={{ width: "100%" }} />
                  </label>
                  <label><strong>Thèmes (virgules)</strong>
                    <input value={edits[job.id]?.themes ?? (job.suggested_themes ?? []).join(", ")} onChange={(ev) => setEdits((s) => ({ ...s, [job.id]: { ...(s[job.id] ?? { category: job.suggested_category ?? "", themes: (job.suggested_themes ?? []).join(", "), folder: job.suggested_folder ?? "" }), themes: ev.target.value } }))} style={{ width: "100%" }} />
                  </label>
                  <div><strong>Langue</strong><div>{job.suggested_language ?? "—"}</div></div>
                  <label><strong>Dossier suggéré</strong>
                    <input value={edits[job.id]?.folder ?? job.suggested_folder ?? ""} onChange={(ev) => setEdits((s) => ({ ...s, [job.id]: { ...(s[job.id] ?? { category: job.suggested_category ?? "", themes: (job.suggested_themes ?? []).join(", "), folder: job.suggested_folder ?? "" }), folder: ev.target.value } }))} style={{ width: "100%" }} />
                  </label>
                </div>
                <details style={{ marginTop: 10, fontSize: 13 }}>
                  <summary style={{ cursor: "pointer" }}>Détails qualité / technique</summary>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 6, marginTop: 8, opacity: 0.9 }}>
                    <div><strong>Durée</strong><div>{q?.duration_s ? `${String(q.duration_s)}s` : "—"}</div></div>
                    <div><strong>Bitrate</strong><div>{q?.bit_rate ? `${Math.round(Number(q.bit_rate)/1000)} kbps` : "—"}</div></div>
                    <div><strong>Sample rate</strong><div>{q?.sample_rate_hz ? `${q.sample_rate_hz} Hz` : "—"}</div></div>
                    <div><strong>Canaux</strong><div>{q?.channels != null ? String(q.channels) : "—"}</div></div>
                    <div><strong>Codec</strong><div>{String(q?.codec ?? "—")}</div></div>
                    <div><strong>Score technique</strong><div>{q?.technical_score != null ? String(q.technical_score) : "—"}/100</div></div>
                    <div><strong>Taille</strong><div>{fmtBytes(job.object?.size_bytes)}</div></div>
                  </div>
                  {job.reason ? <div style={{ marginTop: 8 }}><strong>Raison :</strong> {job.reason}</div> : null}
                  {job.transcript_excerpt ? <div style={{ marginTop: 6 }}><strong>Extrait :</strong> {job.transcript_excerpt}</div> : null}
                </details>
              </article>
            );
          })}
        </div>
      )}
      <ToastStack toasts={toasts} onDismiss={(id) => setToasts((cur) => cur.filter((t) => t.id !== id))} />
    </div>
  );
}
