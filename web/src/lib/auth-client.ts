import { createAuthClient } from "better-auth/react";

/**
 * Better Auth client. Sessions live in HttpOnly cookies managed by the
 * auth service; this app never sees passwords, tokens, or S3 keys.
 * Same-origin relative baseURL: no backend address in the bundle.
 */
export const authClient = createAuthClient({
  // Same-origin at runtime (no backend address baked into the bundle).
  // Dev: Vite proxies /api/auth to the local auth service (see vite.config.ts).
  // Pilot (#21): Traefik routes same-origin /api/auth to the auth service.
  baseURL: `${window.location.origin}/api/auth`,
});

export const { useSession, signIn, signOut } = authClient;
