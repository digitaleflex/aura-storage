import { defineConfig } from "@playwright/test";

// Smoke tests run against servers started manually (see web/README.md):
//   API dev  -> http://127.0.0.1:8081 (uvicorn, SQLite :memory:, dummy S3 creds)
//   Frontend -> http://127.0.0.1:5173 (vite dev, proxies /api to the API above)
// No webServer block on purpose: the API needs explicit dummy-secret env and
// must never point at real storage during tests.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  // The catalogue repository serializes access to its single shared connection
  // (api/dblock.py), so concurrent admin requests no longer flake; no retry is
  // needed to keep this suite stable.
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:5173",
    launchOptions: {
      // Headless environments without GPU: avoid the gpu-process sandbox
      // crash seen with the default flags.
      args: ["--disable-gpu", "--disable-software-rasterizer"],
    },
  },
});
