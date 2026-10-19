import { test, expect } from "@playwright/test";

/**
 * UI v2 step 4: the login page. The login endpoint is mocked (a real wrong
 * password would count against the API's per-IP login rate limit shared with
 * the other suites); nothing touches the catalogue or S3.
 */

test("the password can be revealed and a refusal is flagged on the field", async ({
  page,
}) => {
  await page.route("**/api/v1/login", (route) =>
    route.fulfill({ status: 401, json: { detail: "invalid credentials" } }),
  );
  await page.goto("/login");

  const password = page.getByLabel("Mot de passe");
  await expect(password).toHaveAttribute("type", "password");
  await password.fill("secret-de-test");

  // The toggle is outside the field's label, so the label still names one control.
  const toggle = page.getByRole("button", { name: "Afficher" });
  await toggle.click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(page.getByRole("button", { name: "Masquer" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Masquer" }).click();
  await expect(password).toHaveAttribute("type", "password");

  await page.getByLabel("Identifiant").fill("admin");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Identifiants invalides");
  await expect(password).toHaveAttribute("aria-invalid", "true");
});

test("on a phone the presentation band spans the width and the form follows it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");

  const band = await page.getByRole("region", { name: "Présentation" }).boundingBox();
  const form = await page.getByRole("heading", { name: "Connexion" }).boundingBox();
  expect(band?.width).toBeGreaterThanOrEqual(389);
  // A short band, not one stretched over half the screen.
  expect(band?.height).toBeLessThan(160);
  expect(form?.y ?? 0).toBeGreaterThan((band?.y ?? 0) + (band?.height ?? 0));
  await expect(page.getByLabel("Mot de passe")).toBeVisible();
});

test("the ledger checkboxes are large enough to tap", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/login") {
      await route.fulfill({ json: { csrf_token: "csrf-test" } });
    } else if (path === "/api/v1/me") {
      await route.fulfill({
        json: {
          id: "u1", kind: "user", name: "admin", role: "admin", space_id: "s1",
          application_id: "a1", scopes: ["objects:read"], csrf_token: "csrf-test",
        },
      });
    } else if (path === "/api/v1/folders") {
      await route.fulfill({ json: { items: [] } });
    } else if (path === "/api/v1/objects") {
      await route.fulfill({
        json: {
          items: [{
            id: "obj-1", display_name: "notes.pdf", content_type: "application/pdf",
            size_bytes: 11, status: "available", folder_id: null,
            checksum_sha256: "a".repeat(64), created_at: 1_700_000_000,
            updated_at: 1_700_000_000,
          }],
        },
      });
    } else {
      await route.fulfill({ status: 404, json: { detail: "not mocked" } });
    }
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("pw");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();

  const box = await page.getByLabel("Sélectionner notes.pdf").boundingBox();
  expect(box?.width).toBeGreaterThanOrEqual(18);
  expect(box?.height).toBeGreaterThanOrEqual(18);
});
