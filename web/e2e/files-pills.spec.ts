import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

/**
 * File-family pills on the Files page. Each pill is a preset of the server-side
 * filters, so the test asserts on the requests the UI actually issues.
 */

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes fichiers" })).toBeVisible();
}

function listRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (/\/api\/v1\/objects\?/.test(url)) urls.push(decodeURIComponent(url));
  });
  return urls;
}

const pill = (page: Page, name: string) =>
  page.getByRole("group", { name: "Famille de fichiers" }).getByRole("button", { name });

test("the pills filter by file family on the server", async ({ page }) => {
  const urls = listRequests(page);
  await login(page);

  // "Tous" is the default: pressed, and no media type or status is requested.
  await expect(pill(page, "Tous")).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => urls.length).toBeGreaterThan(0);
  expect(urls.at(-1)).not.toContain("content_type=");

  await pill(page, "Images").click();
  await expect(pill(page, "Images")).toHaveAttribute("aria-pressed", "true");
  await expect(pill(page, "Tous")).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => urls.at(-1)).toContain("content_type=image/*");

  await pill(page, "Audio et vidéo").click();
  await expect.poll(() => urls.at(-1)).toContain("content_type=audio/*,video/*");

  await pill(page, "Documents").click();
  await expect.poll(() => urls.at(-1)).toContain("application/pdf,text/*");

  // "À traiter" switches to the failed status and drops the media types.
  await pill(page, "À traiter").click();
  await expect.poll(() => urls.at(-1)).toContain("status=failed");
  expect(urls.at(-1)).not.toContain("content_type=");

  // "Tous" clears everything again. The unfiltered list is served from the
  // query cache, so the observable effect is the pressed state and the reset.
  await pill(page, "Tous").click();
  await expect(pill(page, "Tous")).toHaveAttribute("aria-pressed", "true");
  await expect(pill(page, "À traiter")).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("button", { name: "Réinitialiser" })).toBeDisabled();
});

test("a pill is not counted as an advanced filter, a custom type is", async ({ page }) => {
  await login(page);
  const toggle = page.getByRole("button", { name: /^Filtres/ });

  await pill(page, "Images").click();
  await expect(toggle).toHaveText("Filtres"); // no badge: the pill shows it

  // A hand-typed media type matches no pill: none is pressed, the badge counts it.
  await toggle.click();
  await page.getByLabel("Type MIME").fill("application/zip");
  await expect(pill(page, "Tous")).toHaveAttribute("aria-pressed", "false");
  await expect(pill(page, "Images")).toHaveAttribute("aria-pressed", "false");
  await expect(toggle).toContainText("1");
});
