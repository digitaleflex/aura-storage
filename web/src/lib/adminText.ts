/** Known server notes, in French; unknown ones are shown as received. */
const NOTE_FR: Record<string, string> = {
  unreachable: "injoignable",
  "local process volume; not the object-store capacity":
    "volume local du processus ; ce n'est pas la capacité du stockage d'objets",
  "Degraded storage means uploads/downloads will fail; full data-plane proof requires the live S3 smoke test.":
    "Un stockage dégradé fait échouer les envois et les téléchargements ; la preuve complète du plan de données exige le test S3 réel (smoke test).",
};
export function frenchNote(text: string | undefined | null): string {
  if (!text) return "";
  return NOTE_FR[text] ?? text;
}

/** One readable line for a supervision row, without dangling separators. */
export function healthDetail(
  component: {
    latency_ms?: number;
    uptime_s?: number;
    free_bytes?: number;
    error?: string;
    note?: string;
  },
  formatBytes: (n: number) => string,
): string {
  const parts: string[] = [];
  if (component.latency_ms !== undefined) parts.push(`${component.latency_ms} ms`);
  if (component.uptime_s !== undefined) parts.push(`démarrée depuis ${component.uptime_s} s`);
  if (component.free_bytes !== undefined) parts.push(`libres : ${formatBytes(component.free_bytes)}`);
  if (component.error) parts.push(frenchNote(component.error));
  if (component.note) parts.push(frenchNote(component.note));
  return parts.join(" · ");
}
