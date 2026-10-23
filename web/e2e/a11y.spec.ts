import { test, expect } from "@playwright/test";
import { AxeBuilder } from "@axe-core/playwright";

const LOGIN = async (page: import("@playwright/test").Page, role = "admin") => {
  await page.goto("/login");
  await page.getByLabel("Identifiant").fill(role);
  await page.getByLabel("Mot de passe").fill("local-smoke-test-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await page.waitForURL(role === "admin" ? "/" : "/");
};

test.describe("accessibilite — pages principales", () => {
  test("login desktop", async ({ page }) => {
    await page.goto("/login");
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(results.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);
  });

  test("files page desktop", async ({ page }) => {
    await LOGIN(page);
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(results.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);
  });

  test("transfers page desktop (empty)", async ({ page }) => {
    await LOGIN(page);
    await page.getByRole("link", { name: "Transferts", exact: true }).click();
    await page.waitForURL("/transfers");
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(results.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);
  });

  test("transfers page desktop (completed session)", async ({ page }) => {
    await LOGIN(page);
    await page.getByTestId("files-input").setInputFiles([
      { name: "a.pdf", mimeType: "application/pdf", buffer: Buffer.from("x") },
      { name: "b.pdf", mimeType: "application/pdf", buffer: Buffer.from("x") },
    ]);
    await page.getByRole("button", { name: "Importer et valider" }).click();
    await page.getByRole("link", { name: "Transferts", exact: true }).click();
    await page.waitForURL("/transfers");
    await page.waitForTimeout(500);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(results.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);
  });

  test("admin page desktop", async ({ page }) => {
    await LOGIN(page);
    await page.getByRole("link", { name: "Administration", exact: true }).click();
    await page.waitForURL("/admin");
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(results.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);
  });
});
