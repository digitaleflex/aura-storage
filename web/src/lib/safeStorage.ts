/**
 * localStorage can throw: Safari private mode, disabled storage, quota errors.
 * A read in a useState initializer used to take the whole render down (white
 * screen). Reads fall back to null; writes become no-ops.
 */
export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Preference not persisted: the in-memory state still works.
  }
}
