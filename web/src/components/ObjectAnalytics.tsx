import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

function bytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 o";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/** Per-object usage for the details drawer (real counters, monthly + lifetime). */
export function ObjectAnalytics({ objectId }: { objectId: string }) {
  const query = useQuery({
    queryKey: ["object-analytics", objectId],
    queryFn: () => api.objectAnalytics(objectId),
    retry: false,
    staleTime: 30_000,
  });
  if (query.isPending) return <p className="muted">Chargement des statistiques…</p>;
  if (query.isError || !query.data) return <p className="muted">Statistiques indisponibles.</p>;
  const { month, totals, period } = query.data;
  return (
    <div className="analytics-grid" aria-label="Statistiques de l'objet">
      <div><strong>{month.views}</strong><span>vues ({period})</span></div>
      <div><strong>{month.downloads}</strong><span>téléchargements</span></div>
      <div><strong>{month.share_opens}</strong><span>ouvertures de partage</span></div>
      <div><strong>{bytes(month.egress_bytes)}</strong><span>trafic estimé</span></div>
      <div><strong>{totals.views}</strong><span>vues cumulées</span></div>
      <div><strong>{totals.downloads}</strong><span>téléchargements cumulés</span></div>
    </div>
  );
}
