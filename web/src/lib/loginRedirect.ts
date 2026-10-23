/**
 * Where to go after logging back in. The route guard stores it here instead of
 * in the login URL: the SPA may be served under a subpath (/app), and a raw
 * query parameter is easy to misuse as an open redirect. Per-tab only.
 */
const KEY = "aura-login-redirect-v1";

/** Remember an internal path (guard → login). */
export function rememberLoginRedirect(href: string): void {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  if (!isInternalPath(href)) return;
  try {
    window.sessionStorage.setItem(KEY, href);
  } catch {
    // Private window: returning to the page is a convenience.
  }
}

/** Read and forget the pending redirect, or null when there is none. */
export function consumeLoginRedirect(): string | null {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  try {
    const href = window.sessionStorage.getItem(KEY);
    window.sessionStorage.removeItem(KEY);
    return href && isInternalPath(href) && !href.startsWith("/login") ? href : null;
  } catch {
    return null;
  }
}

function isInternalPath(href: string): boolean {
  return href.startsWith("/") && !href.startsWith("//");
}
