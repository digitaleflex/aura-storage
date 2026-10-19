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
  // The API drives the view: an empty catalogue renders the explicit empty
  // state. Both lists are answered empty here, because other suites create
  // folders at the shared root while this one runs.
  await page.route(/\/api\/v1\/(folders|objects)(\?|$)/, (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await login(page);
  await expect(
    page.getByRole("heading", { name: /^Contenu — / }),
  ).toBeVisible();
  await expect(page.getByText("Aucun fichier dans ce dossier.")).toBeVisible();
});

test("the name filter is applied server-side (not over loaded pages)", async ({
  page,
}) => {
  const objectRequests: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/v1/objects?")) objectRequests.push(url);
  });

  await login(page);

  // The first page carries the default sort/order so the server owns ordering.
  await expect
    .poll(() =>
      objectRequests.some(
        (url) => url.includes("sort=created_at") && url.includes("order=desc"),
      ),
    )
    .toBe(true);

  await page.getByLabel("Rechercher").fill("rapport");
  await expect
    .poll(() => objectRequests.some((url) => url.includes("q=rapport")))
    .toBe(true);
});

test("status and sort controls reach the API", async ({ page }) => {
  const objectRequests: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/v1/objects?")) objectRequests.push(url);
  });

  // The column headers only exist when the list has rows, so answer the object
  // list with one (requests are still observed above).
  await page.route("**/api/v1/objects?*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: "obj-sort", display_name: "tri.pdf", content_type: "application/pdf",
            size_bytes: 11, status: "available", folder_id: null,
            checksum_sha256: "a".repeat(64), created_at: 1_700_000_000,
            updated_at: 1_700_000_000,
          },
        ],
      },
    }),
  );
  await login(page);

  await page.getByLabel("État").selectOption("available");
  await expect
    .poll(() => objectRequests.some((url) => url.includes("status=available")))
    .toBe(true);

  // Sorting happens from the column headers (server-side): the list starts
  // on "Ajouté" descending; a first click on "Nom" sorts A to Z, a second Z to A.
  await page.getByRole("button", { name: /^Nom/ }).click();
  await expect
    .poll(() =>
      objectRequests.some(
        (url) => url.includes("sort=display_name") && url.includes("order=asc"),
      ),
    )
    .toBe(true);
  await page.getByRole("button", { name: /^Nom/ }).click();
  await expect
    .poll(() =>
      objectRequests.some(
        (url) => url.includes("sort=display_name") && url.includes("order=desc"),
      ),
    )
    .toBe(true);
});

test("a search with no match shows an explicit empty state", async ({ page }) => {
  await login(page);
  await page.getByLabel("Rechercher").fill(`zz-no-such-file-${Date.now()}`);
  await expect(
    page.getByText("Aucun fichier ne correspond à ces critères."),
  ).toBeVisible();
  // The details panel is not opened by a search.
  await expect(
    page.getByRole("heading", { name: "Détails de l'objet" }),
  ).toHaveCount(0);
});
