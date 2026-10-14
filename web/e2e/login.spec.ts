import { test, expect } from "@playwright/test";

/**
 * Smoke test: a login with wrong credentials must be rejected.
 * Requires the local API (uvicorn 127.0.0.1:8081, SQLite :memory:) and the
 * Vite dev server (127.0.0.1:5173) running — see web/README.md.
 * Only the /api/v1/login path is exercised; no S3 contact happens on a 401.
 */
test("login with wrong credentials is rejected", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("wrong-password-for-smoke-test");
  await page.getByRole("button", { name: "Log in", exact: true }).click();

  await expect(page.getByRole("alert")).toContainText("Invalid credentials");
  await expect(page).toHaveURL(/\/login/);
});
