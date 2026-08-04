import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { AuthResponse, User } from "../types/api";
import { authApi } from "../lib/services";
import { ApiError } from "../lib/api";
import {
  clearSession,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from "../lib/tokenStore";

interface AuthContextValue {
  user: User | null;
  /** True while the initial GET /auth/me hydration is in flight. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (input: {
    company_name: string;
    email: string;
    password: string;
    full_name?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function applyAuthResponse(resp: AuthResponse, setUser: (u: User) => void) {
  setAccessToken(resp.tokens.access_token);
  setRefreshToken(resp.tokens.refresh_token);
  setUser(resp.user);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Hydrate the session on app load: if a refresh token exists, exchange
    // it for a fresh access token (the in-memory access token does not
    // survive a page reload), then confirm identity with GET /auth/me.
    (async () => {
      const refreshToken = getRefreshToken();
      if (!refreshToken) {
        setLoading(false);
        return;
      }
      try {
        // Reuse the api client's own refresh path by calling /auth/me, which
        // will 401 and trigger the client's built-in refresh-and-retry using
        // the stored refresh token, then hydrate the current user.
        const me = await authApi.me();
        setUser(me);
      } catch {
        clearSession();
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await authApi.login({ email, password });
    applyAuthResponse(resp, setUser);
  }, []);

  const signup = useCallback(
    async (input: { company_name: string; email: string; password: string; full_name?: string }) => {
      const resp = await authApi.signup(input);
      applyAuthResponse(resp, setUser);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch (err) {
      // Already-invalid session, network hiccup, etc. — a failed logout call
      // must not prevent clearing local state.
      if (!(err instanceof ApiError)) throw err;
    } finally {
      clearSession();
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, signup, logout }),
    [user, loading, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

export const OPERATIONS_ROLES: User["role"][] = ["owner", "admin", "office"];

export function canManageOperations(role: User["role"] | undefined): boolean {
  return !!role && OPERATIONS_ROLES.includes(role);
}

export function canManageUsers(role: User["role"] | undefined): boolean {
  return role === "owner" || role === "admin";
}
