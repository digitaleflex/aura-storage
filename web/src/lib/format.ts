/**
 * Display formatting for the transfers console.
 *
 * Binary units and the same "Ko/Mo/Go" labels as the rest of the product, so a
 * size reads identically on the files page and on the transfers page.
 */
const BYTE_UNITS = ["o", "Ko", "Mo", "Go", "To"];

export function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return "—";
  if (size === 0) return "0 o";
  const index = Math.min(
    Math.floor(Math.log(size) / Math.log(1024)),
    BYTE_UNITS.length - 1,
  );
  const value = size / 1024 ** index;
  return `${value.toFixed(index === 0 ? 0 : 1)} ${BYTE_UNITS[index]}`;
}

export function formatRate(bytesPerSecond: number): string {
  if (!Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return "—";
  return `${formatBytes(Math.round(bytesPerSecond))}/s`;
}

/** "~ 13 min", "~ 45 s", "~ 2 h 05 min"; null when no honest estimate exists. */
export function formatRemaining(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds <= 0) {
    return "Indisponible";
  }
  if (seconds < 45) return `~ ${Math.ceil(seconds)} s`;
  const totalMinutes = Math.ceil(seconds / 60);
  if (totalMinutes < 60) return `~ ${totalMinutes} min`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours >= 24) return "> 24 h";
  return `~ ${hours} h${minutes > 0 ? ` ${String(minutes).padStart(2, "0")} min` : ""}`;
}

const TIME_FORMAT = new Intl.DateTimeFormat("fr-FR", {
  hour: "2-digit",
  minute: "2-digit",
});

export function formatClock(epochMs: number): string {
  return TIME_FORMAT.format(new Date(epochMs));
}

const MS_FORMAT = new Intl.NumberFormat("fr-FR");

export function formatMilliseconds(value: number): string {
  return `${MS_FORMAT.format(Math.round(value))}\u00A0ms`;
}

/** Parse a size typed in mebibytes; NaN/empty gives null (no constraint). */
export function parseMegabytes(value: string): number | null {
  const normalized = value.replace(",", ".").trim();
  if (normalized === "") return null;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return parsed * 1024 * 1024;
}

/** "0:42", "12:05", "1 h 03 min" — elapsed or estimated duration. */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds > 0 && seconds < 1) return "< 1 s";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours} h ${String(minutes).padStart(2, "0")} min`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

/** "MP4", "PDF", "ZIP" — extension shown as a small type hint. */
export function fileExtension(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  if (dot < 0 || dot === fileName.length - 1) return "";
  return fileName.slice(dot + 1).toUpperCase();
}
