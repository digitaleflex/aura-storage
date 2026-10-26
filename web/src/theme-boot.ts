/**
 * Apply the stored theme before React renders.
 *
 * This used to be an inline <script> in index.html, which the production CSP
 * (`script-src 'self'`) blocks: the theme silently stopped being applied and
 * the light/dark flash came back. Running it from a module keeps the same
 * "before first paint" effect without weakening the CSP.
 */
try {
  const savedTheme = localStorage.getItem("aura-theme");
  if (savedTheme === "dark" || savedTheme === "light") {
    document.documentElement.setAttribute("data-theme", savedTheme);
  }
} catch {
  // Storage unavailable (private mode, quota): keep the system preference.
}

export {};
