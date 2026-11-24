import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

/**
 * Tag filter on the Files page. The input is the missing UI for the `tag`
 * query field already supported by the API; assert on the requests the UI
 * issues, not on catalogue contents.
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

test("the tag input filters on the server and normalizes case", async ({ page }) => {
  const urls = listRequests(page);
  await login(page);

  await page.getByRole("button", { name: /^Filtres/ }).click();
  const input = page.locator('input[name="tag"]');
  await expect(input).toBeVisible();

  await input.fill("MATHS");
  await expect.poll(() => urls.at(-1)).toContain("tag=maths");

  // The tag is an advanced filter: it counts in the badge and enables reset.
  await expect(page.getByRole("button", { name: /^Filtres/ })).toContainText("1");
  const reset = page.getByRole("button", { name: "Réinitialiser" });
  await expect(reset).toBeEnabled();

  await reset.click();
  await expect(input).toHaveValue("");
  await expect(page.getByRole("button", { name: /^Filtres/ })).toHaveText("Filtres");
  await expect(reset).toBeDisabled();
});

test("the tag filter leaves file-family pills alone", async ({ page }) => {
  await login(page);
  const pills = page.getByRole("group", { name: "Famille de fichiers" });
  await pills.getByRole("button", { name: "Images" }).click();

  await page.getByRole("button", { name: /^Filtres/ }).click();
  await page.locator('input[name="tag"]').fill("l1");

  await expect(pills.getByRole("button", { name: "Images" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByRole("button", { name: /^Filtres/ })).toContainText("1");
});

test("several tags are sent with an all/any combination mode", async ({ page }) => {
  const urls = listRequests(page);
  await login(page);
  await page.getByRole("button", { name: /^Filtres/ }).click();

  await page.locator('input[name="tag"]').fill("MATHS, l1");
  await expect.poll(() => urls.at(-1)).toContain("tags=maths,l1");
  await expect.poll(() => urls.at(-1)).toContain("tag_mode=all");
  expect(urls.at(-1)).not.toContain("tag=maths");

  await page.getByLabel("Combinaison").selectOption("any");
  await expect.poll(() => urls.at(-1)).toContain("tag_mode=any");
});
