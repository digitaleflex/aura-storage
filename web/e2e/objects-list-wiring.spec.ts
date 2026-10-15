import { test, expect } from "@playwright/test";

/**
 * Wiring checks for the paged object list and the flat folder tree.
 *
 * Asserts on the requests the UI actually issues, so no seeded data is needed
 * (uploads are never performed in e2e: they would need real storage). It fails if
 * the folder browser regresses to the per-level breadth-first listing, or if the
 * object table stops asking for a page.
 *
 * Requires the local API (uvicorn, SQLite :memory:, dummy S3 creds,
 * AURA_API_ADMIN_PASSWORD=local-smoke-test-password) and the Vite dev server —
 * see web/README.md.
 */

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fichiers" })).toBeVisible();
}

test("folder tree is fetched flat in one request and objects are paged", async ({
  page,
}) => {
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/v1/")) {
      apiRequests.push(url);
    }
  });

  await login(page);

  // One request for the whole tree instead of one per level.
  const flatTree = apiRequests.filter((url) =>
    url.includes("/api/v1/folders?all=true"),
  );
  expect(flatTree).toHaveLength(1);

  // No per-level walk (the pre-#62-follow-up behaviour) remains.
  const perLevel = apiRequests.filter((url) =>
    /\/api\/v1\/folders\?parent_id=/.test(url),
  );
  expect(perLevel).toHaveLength(0);

  // The object table asks the API for its first page explicitly.
  const objectList = apiRequests.find((url) => url.includes("/api/v1/objects?"));
  expect(objectList, "the UI must request the object list").toBeTruthy();
  expect(objectList).toContain("limit=50");
  expect(objectList).toContain("offset=0");
});

test("the folders tab shows the empty state rather than fake data", async ({
  page,
}) => {
  await login(page);
  // The API drives the view: whatever it returns is rendered as-is.
  await expect(
    page.getByRole("heading", { name: /^Objets — / }),
  ).toBeVisible();
  await expect(
    page.getByText(/Aucun sous-dossier ici\.|Aucun fichier dans ce dossier\./).first(),
  ).toBeVisible();
});
