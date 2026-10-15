import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate } from "@tanstack/react-router";
import { api, ApiError } from "./api";
import type { SessionInfo } from "./api";

interface AuthState {
  /** CSRF token kept in memory only; never persisted. Null = not logged in. */
  csrf: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [csrf, setCsrf] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api.login(username, password);
      setCsrf(res.csrf_token);
      // Refresh the server-verified session (role, scopes) for this identity.
      await queryClient.invalidateQueries({ queryKey: ["session"] });
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    if (csrf) {
      try {
        await api.logout(csrf);
      } catch (err) {
        // Session may already be gone; still clear local state.
        if (!(err instanceof ApiError && err.status === 401)) {
          throw err;
        }
      }
    }
    setCsrf(null);
    await queryClient.invalidateQueries({ queryKey: ["session"] });
  }, [csrf, queryClient]);

  const value = useMemo(() => ({ csrf, login, logout }), [csrf, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>.");
  }
  return ctx;
}

/**
 * Server-verified session metadata (`GET /api/v1/me`). Shared query key with
 * RequireAuth, so the role read here is the same one the guard resolved.
 */
export function useSession() {
  return useQuery<SessionInfo>({
    queryKey: ["session"],
    queryFn: () => api.me(),
    retry: false,
  });
}

/**
 * Route guard verified against the SERVER, not memory: works right after
 * login (no state-flush race) and survives page reloads while the session
 * cookie is valid. Renders nothing while checking to avoid flashing login.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const sessionQuery = useSession();

  if (sessionQuery.isPending) {
    return <p className="muted">Vérification de la session…</p>;
  }
  if (sessionQuery.isError) {
    return <Navigate to="/login" />;
  }
  return <>{children}</>;
}
