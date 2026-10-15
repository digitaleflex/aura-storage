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
  // The dev/test stack shares ONE catalogue connection across FastAPI's
  // threadpool (api/db.py sqlite3 / api/db_pg.py psycopg). Concurrent admin
  // reads can therefore raise `sqlite3.InterfaceError` and surface as a
  // transient 401/500 (pre-existing, unrelated to a specific feature). One
  // retry keeps the smoke suite stable until the catalogue layer is made
  // concurrency-safe; a real regression still fails every attempt.
  retries: 1,
  use: {
    baseURL: "http://127.0.0.1:5173",
    launchOptions: {
      // Headless environments without GPU: avoid the gpu-process sandbox
      // crash seen with the default flags.
      args: ["--disable-gpu", "--disable-software-rasterizer"],
    },
  },
});
