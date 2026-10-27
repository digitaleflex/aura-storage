// Capture desktop/mobile screenshots of the Transfers page for design review.
// Usage:
//   AURA_CAPTURE_USER=... AURA_CAPTURE_PASSWORD=... node web/capture-transfers.cjs
// Credentials are read from the environment and never stored in this file.
const { chromium } = require("playwright");

const APP_URL = process.env.AURA_CAPTURE_URL || "https://app.aura-storage.eurinhash.com";
const USER = process.env.AURA_CAPTURE_USER;
const PASSWORD = process.env.AURA_CAPTURE_PASSWORD;
if (!USER || !PASSWORD) {
  console.error("AURA_CAPTURE_USER and AURA_CAPTURE_PASSWORD are required");
  process.exit(1);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--disable-gpu", "--disable-software-rasterizer", "--no-sandbox"],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });

  // Intercepter les requêtes d'écriture réelles vers le stockage pour rester en lecture seule
  // (on ne bloque pas le login, on bloque juste les PUT/POST vers l'upload)
  await page.route("**/api/v1/objects/**", (route) => {
    const m = route.request().method();
    if (m === "PUT" || m === "POST" || m === "DELETE") {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, audit_readonly: true }),
      });
      return;
    }
    route.continue();
  });

  await page.goto(`${APP_URL}/login`, {
    waitUntil: "networkidle",
    timeout: 30000,
  });

  await page.getByLabel(/Identifiant/i).fill(USER);
  await page.getByLabel(/Mot de passe/i).fill(PASSWORD);
  await page.getByRole("button", { name: /Se connecter/ }).click();

  // Attendre d'arriver sur /transfers (après login, redirection probable vers la page d'accueil)
  await page.waitForURL(/.*/, { timeout: 30000 });
  await page.goto(`${APP_URL}/transfers`, {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  await page.waitForTimeout(1500); // laisser les animations/états se stabiliser

  await page.screenshot({
    path: "/tmp/opencode/transfers-desktop.png",
    fullPage: true,
  });

  // Mobile
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(800);
  await page.screenshot({
    path: "/tmp/opencode/transfers-mobile.png",
    fullPage: true,
  });

  await browser.close();
  console.log("DONE");
})();
