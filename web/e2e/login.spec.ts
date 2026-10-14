import { test, expect } from "@playwright/test";

/**
 * Smoke tests for the Google sign-in gate.
 * Requires the Vite dev server (127.0.0.1:5173) running — see web/README.md.
 * Google OAuth itself cannot run headless here; these tests assert the gate:
 * unauthenticated users stay on /login with the Google button, and the
 * protected catalogue never renders without a session.
 */
test("login page offers Google sign-in only", async ({ page }) => {
  await page.goto("/login");

  await expect(
    page.getByRole("button", { name: "Sign in with Google" })
  ).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
});

test("protected catalogue redirects to login when anonymous", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});
