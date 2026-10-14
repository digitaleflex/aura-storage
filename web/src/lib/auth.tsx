import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";
import { Navigate } from "@tanstack/react-router";
import { signIn, signOut, useSession } from "./auth-client";

interface AuthState {
  userEmail: string | null;
  pending: boolean;
  loginWithGoogle: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data, isPending } = useSession();

  const value = useMemo<AuthState>(
    () => ({
      userEmail: data?.user?.email ?? null,
      pending: isPending,
      loginWithGoogle: async () => {
        await signIn.social({ provider: "google", callbackURL: "/" });
      },
      logout: async () => {
        await signOut();
      },
    }),
    [data, isPending]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { userEmail, pending } = useAuth();
  if (pending) return <p>Chargement…</p>;
  if (!userEmail) return <Navigate to="/login" />;
  return <>{children}</>;
}
