import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate } from "@tanstack/react-router";
import { api, ApiError } from "./api";
import type { SessionInfo } from "./api";
import { clearFilesView } from "./filesViewState";
import { rememberLoginRedirect } from "./loginRedirect";

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
  // Server-verified session; shares the query key with RequireAuth, so this
  // costs no extra request. The CSRF token is never persisted: it is
  // re-hydrated from /me after a reload/new tab (csrf is memory-only).
  const session = useSession();
  // Last token adopted from /me. Lets us ignore stale cached session data
  // (e.g. during the refetch that follows logout) and avoids re-arming the
  // token after an explicit logout.
  const hydratedToken = useRef<string | null>(null);

  useEffect(() => {
    const token = session.data?.csrf_token ?? null;
    if (!token || token === hydratedToken.current) return;
    hydratedToken.current = token;
    // Only fill an empty slot so a value set by login() is never overwritten.
    setCsrf((current) => current ?? token);
  }, [session.data]);

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
    clearFilesView();
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
  const location = useLocation();
  const navigate = useNavigate();

  // Keep the page the user was on: after logging back in, the login page
  // returns there instead of dumping everyone on the root folder. Stored in
  // sessionStorage rather than a query string (subpath-safe, no open redirect).
  useEffect(() => {
    if (!sessionQuery.isError) return;
    rememberLoginRedirect(location.href);
    void navigate({ to: "/login", replace: true });
  }, [sessionQuery.isError, location.href, navigate]);

  if (sessionQuery.isPending) {
    return <p className="muted">Vérification de la session…</p>;
  }
  if (sessionQuery.isError) {
    return <p className="muted">Redirection vers la connexion…</p>;
  }
  return <>{children}</>;
}
