import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

/**
 * Browser-level coverage of issue #319: the add-to-playlist dialog on a public
 * catalogue card. The portal markup is the same native <dialog> shipped by
 * api/public_ui.py; only the four authenticated API responses are stubbed so
 * the spec runs without a real public account or published book.
 */
const script = fileURLToPath(
  new URL("../../api/portal_assets/playlists.js", import.meta.url),
);

const pageHtml = `<!doctype html><html lang="fr"><head>
<base href="http://portal.test/">
<meta charset="utf-8"><meta name="csrf-token" content="test-csrf-token">
</head><body>
<ul class="shelf"><li>
  <button type="button" class="track-button"><span class="track-title">La Nuit</span></button>
  <button type="button" class="playlist-add-button" data-add-playlist="book-1"
    aria-haspopup="dialog" aria-label="Ajouter à une liste : La Nuit"><span aria-hidden="true">+</span></button>
</li></ul>
<dialog id="playlist-dialog" aria-labelledby="playlist-dialog-title">
  <div class="playlist-dialog-head">
    <h3 id="playlist-dialog-title">Ajouter à une liste</h3>
    <button type="button" id="playlist-dialog-close" aria-label="Fermer">×</button>
  </div>
  <p id="playlist-dialog-book"></p>
  <div id="playlist-dialog-status" class="playlist-dialog-status" role="status" aria-live="polite"></div>
  <div id="playlist-dialog-list" aria-label="Listes de lecture"></div>
  <form id="playlist-create-form">
    <label for="playlist-create-name">Nouvelle liste</label>
    <input id="playlist-create-name" name="name" type="text" required>
    <button type="submit">Créer</button>
  </form>
</dialog>
</body></html>`;

type Playlist = { id: string; name: string; item_count: number };

async function openPortal(page: import("@playwright/test").Page, options: {
  playlists?: Playlist[];
  addStatus?: number;
  onAdd?: () => void;
} = {}) {
  const playlists = options.playlists ?? [{ id: "p1", name: "À relire", item_count: 0 }];
  await page.setContent(pageHtml);
  await page.route("**/api/public/playlists**", async (route) => {
    const method = route.request().method();
    const path = new URL(route.request().url()).pathname;
    expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf-token");
    if (path === "/api/public/playlists" && method === "GET") {
      await route.fulfill({ json: { playlists } });
      return;
    }
    if (path === "/api/public/playlists" && method === "POST") {
      const name = String(route.request().postDataJSON().name ?? "Nouvelle liste");
      playlists.push({ id: `p${playlists.length + 1}`, name, item_count: 0 });
      await route.fulfill({ json: { playlist: playlists[playlists.length - 1] } });
      return;
    }
    if (path.endsWith("/items/book-1") && method === "PUT") {
      options.onAdd?.();
      await route.fulfill({
        status: options.addStatus ?? 200,
        json: options.addStatus
          ? { detail: "object not published" }
          : { object_id: "book-1", added: true },
      });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: "unexpected request" } });
  });
  await page.addScriptTag({ path: script });
  await page.getByRole("button", { name: "Ajouter à une liste : La Nuit" }).click();
  await expect(page.locator("#playlist-dialog")).toBeVisible();
}

test("the card button opens the dialog and confirms an idempotent add", async ({ page }) => {
  await openPortal(page);
  await expect(page.getByText("À relire")).toBeVisible();
  await page.getByRole("button", { name: /À relire/ }).click();
  await expect(page.locator("#playlist-dialog-status")).toHaveText("Livre ajouté à la liste.");
  await expect(page.getByRole("button", { name: /À relire/ })).toContainText("Ajouté");
  await expect(page.getByRole("button", { name: /À relire/ })).toBeDisabled();
});

test("a playlist can be created from the dialog and immediately selected", async ({ page }) => {
  await openPortal(page);
  await page.getByLabel("Nouvelle liste").fill("À relire plus tard");
  await page.getByRole("button", { name: "Créer" }).click();
  await expect(page.getByRole("button", { name: /À relire plus tard/ })).toBeVisible();
  await page.getByRole("button", { name: /À relire plus tard/ }).click();
  await expect(page.locator("#playlist-dialog-status")).toHaveText("Livre ajouté à la liste.");
});

test("an API failure is surfaced and the choice can be retried", async ({ page }) => {
  await openPortal(page, { addStatus: 500 });
  await page.getByRole("button", { name: /À relire/ }).click();
  await expect(page.locator("#playlist-dialog-status")).toHaveText(
    "Impossible d’ajouter ce livre à la liste.",
  );
  await expect(page.locator("#playlist-dialog-status")).toHaveClass(/is-error/);
  await expect(page.getByRole("button", { name: /À relire/ })).toBeEnabled();
});
