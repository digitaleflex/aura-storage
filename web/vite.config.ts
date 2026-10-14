import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only proxy target for the management API (same process serves the
// static build in production, so the app itself only uses relative paths).
const API_TARGET = process.env.AURA_API_PROXY ?? "http://127.0.0.1:8081";

// Subpath deployment: VITE_SUBPATH=/app builds for https://host/app/.
// Dev default serves at /.
const SUBPATH = (process.env.VITE_SUBPATH ?? "").replace(/\/$/, "");

export default defineConfig({
  base: SUBPATH ? `${SUBPATH}/` : "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
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
