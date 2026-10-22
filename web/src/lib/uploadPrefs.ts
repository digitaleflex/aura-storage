/** Per-browser upload preferences. Storage may be unavailable (private mode,
 * blocked): every access is guarded and falls back to the default. */
const KEY = "aura.upload.concurrency";
export const CONCURRENCY_CHOICES = [1, 2, 3, 4] as const;
export const DEFAULT_CONCURRENCY_CHOICE = 4;

export function readConcurrencyPref(): number {
  try {
    const raw = window.localStorage.getItem(KEY);
    const value = raw === null ? NaN : Number(raw);
    return (CONCURRENCY_CHOICES as readonly number[]).includes(value)
      ? value
      : DEFAULT_CONCURRENCY_CHOICE;
  } catch {
    return DEFAULT_CONCURRENCY_CHOICE;
  }
}

export function writeConcurrencyPref(value: number): void {
  try {
    window.localStorage.setItem(KEY, String(value));
  } catch {
    // Not persisted: the choice still applies to the running queue.
  }
}
