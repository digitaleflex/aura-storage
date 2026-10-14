import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only proxy targets (production serves same-origin via Traefik, #21).
const API_TARGET = process.env.AURA_API_PROXY ?? "http://127.0.0.1:8081";
const AUTH_TARGET = process.env.AURA_AUTH_PROXY ?? "http://127.0.0.1:8099";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api/auth": { target: AUTH_TARGET, changeOrigin: false },
      "/api": { target: API_TARGET, changeOrigin: false },
      "/health": { target: API_TARGET, changeOrigin: false },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 600,
  },
});
