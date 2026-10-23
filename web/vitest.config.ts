import { defineConfig } from "vitest/config";

// Unit tests live next to the code they exercise (*.test.ts). They target the
// pure helpers only (model.ts, format.ts): no DOM, no React, no network.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    reporters: ["default"],
  },
});
