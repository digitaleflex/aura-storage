import { Hono } from "hono";
import { serve } from "@hono/node-server";
import { auth } from "./auth.js";

const app = new Hono();

app.on(["POST", "GET"], "/api/auth/*", (c) => auth.handler(c.req.raw));

app.get("/health", (c) => c.json({ status: "ok" }));

const port = Number(process.env.AUTH_PORT || 8099);
serve({ fetch: app.fetch, port, hostname: "127.0.0.1" });
console.log(`aura-auth listening on 127.0.0.1:${port}`);
