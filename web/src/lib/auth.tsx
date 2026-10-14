import { useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate } from "@tanstack/react-router";
import { api, ApiError } from "./api";

interface AuthState {
  /** CSRF token kept in memory only; never persisted. Null = not logged in. */
  csrf: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [csrf, setCsrf] = useState<string | null>(null);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    setCsrf(res.csrf_token);
  }, []);

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
  }, [csrf]);

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
 * Route guard verified against the SERVER, not memory: works right after
 * login (no state-flush race) and survives page reloads while the session
 * cookie is valid. Renders nothing while checking to avoid flashing login.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const sessionQuery = useQuery({
    queryKey: ["session"],
    queryFn: () => api.me(),
    retry: false,
  });

  if (sessionQuery.isPending) {
    return <p className="muted">Vérification de la session…</p>;
  }
  if (sessionQuery.isError) {
    return <Navigate to="/login" />;
  }
  return <>{children}</>;
}
