import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { ApiError, PresignedUploadError } from "../src/lib/api";
import { describeError } from "../src/lib/errors";

/**
 * Clear messages and visible waiting: API details become French sentences a
 * person can act on, and a slow admin section says it is still working.
 */

test("API details become actionable French messages", () => {
  expect(describeError(new ApiError(409, "object not available"), "x")).toContain(
    "pas encore disponible",
  );
  expect(describeError(new ApiError(507, "anything"), "x")).toContain("Espace de stockage plein");
  expect(describeError(new ApiError(401, "not authenticated"), "x")).toContain("session a expiré");
  expect(describeError(new ApiError(502, "bad gateway"), "x")).toContain("Réessayez");
  // The server's exact string for a non-empty folder (409) is mapped: without
  // it, deleting a folder holding files rendered "L'élément a changé".
  expect(describeError(new ApiError(409, "folder is not empty"), "x")).toContain("pas vide");
  expect(describeError(new TypeError("Failed to fetch"), "x")).toContain("Vérifiez votre réseau");
  expect(describeError(new PresignedUploadError("network", 0, "x"), "y")).toBe(
    "Connexion au stockage interrompue.",
  );
  // An unknown detail keeps the caller's own sentence, never a raw code.
  expect(describeError(new ApiError(418, "teapot"), "Action impossible.")).toBe("Action impossible.");
});

async function loginToAdmin(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page).toHaveURL(/\/admin/);
}

test("a slow supervision says what it is doing, then that it is slow", async ({ page }) => {
  await page.route("**/api/v1/admin/health", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 6000));
    await route.continue();
  });
  await loginToAdmin(page);
  const section = page.getByRole("region", { name: "Supervision" });
  await expect(section.getByRole("status")).toContainText("Vérification des services");
  // The waiting state is styled (a lost stylesheet block once left it bare).
  await expect(section.locator(".loading")).toHaveCSS("display", "flex");
  await expect(section.locator(".loading .spinner")).toHaveCSS("animation-name", "spin");
  await expect(section.getByRole("status")).toContainText("met du temps à répondre", {
    timeout: 8000,
  });
});

test("a failed section explains why and can be retried", async ({ page }) => {
  // The files page also reads usage; fail every call until the retry.
  let failing = true;
  await page.route("**/api/v1/admin/usage", async (route) => {
    if (failing) {
      await route.fulfill({ status: 503, json: { detail: "service unavailable" } });
    } else {
      await route.continue();
    }
  });
  await loginToAdmin(page);
  const alert = page.getByRole("region", { name: "Consommation" }).getByRole("alert");
  await expect(alert).toContainText("Consommation indisponible.");
  await expect(alert).toContainText("Réessayez dans un instant");
  failing = false;
  await alert.getByRole("button", { name: "Réessayer" }).click();
  await expect(page.getByRole("region", { name: "Consommation" }).getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("Octets vérifiés").first()).toBeVisible();
});
