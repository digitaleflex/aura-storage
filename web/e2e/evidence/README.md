# UI evidence

- `login-desktop.png`, `login-mobile.png`, `objects-empty.png`: captured from the
  running app by the Playwright specs (real end-to-end output).
- `registre-desktop.png`, `registre-mobile.png`: **design references** for the
  « Registre » direction (PR #77). Captured from the app with a mocked API and
  sample data — not live end-to-end output; no real storage was used.

Sample-data screenshots exist because the real app needs an authenticated
session plus SeaweedFS objects, which the offline setup cannot provide; the
empty-state screenshot above is the real end-to-end one.
