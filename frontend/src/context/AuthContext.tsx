import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { AuthResponse, LoginMfaRequiredResponse, User } from "../types/api";
import { AuthContext } from "./auth";
import { authApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { clearSession, getCsrfToken, setAccessToken } from "../lib/tokenStore";
import { wipeFieldOfflineData } from "../lib/offlineDb";

// Discriminates the two possible POST /auth/login response shapes. Kept
// here (rather than as a type-guard export from types/api.ts) since it is
// only ever used at this one call site.
function isMfaRequired(
  resp: AuthResponse | LoginMfaRequiredResponse,
): resp is LoginMfaRequiredResponse {
  return "mfa_required" in resp;
}

function applyAuthResponse(resp: AuthResponse, setUser: (u: User) => void) {
  setAccessToken(resp.tokens.access_token);
  // Phase 16: the refresh token is no longer handed to the frontend at all
  // -- the backend already set it as an httpOnly cookie on this same
  // response (see app/api/v1/routes/auth.py::_set_refresh_cookie). There is
  // nothing left for this function to store for it.
  setUser(resp.user);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Hydrate the session on app load. Phase 16: there is no
    // frontend-readable refresh token anymore to gate this on (it's an
    // httpOnly cookie) -- the readable signal that a session MIGHT exist is
    // the paired CSRF cookie (`getCsrfToken`), which the backend sets
    // alongside the refresh cookie on every login/signup/refresh. If it's
    // absent, no one has ever logged in on this browser (or it expired
    // alongside the refresh cookie), so skip straight to "logged out" rather
    // than firing a request that can only 401.
    //
    // If it IS present, call GET /auth/me: the in-memory access token never
    // survives a page reload, so this first call 401s, which triggers the
    // api client's built-in refresh-and-retry (see src/lib/api.ts) using the
    // httpOnly cookie, and only then resolves with the current user.
    (async () => {
      if (!getCsrfToken()) {
        setLoading(false);
        return;
      }
      try {
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
    if (isMfaRequired(resp)) {
      return { preAuthToken: resp.pre_auth_token };
    }
    applyAuthResponse(resp, setUser);
  }, []);

  const loginMfa = useCallback(async (preAuthToken: string, code: string) => {
    const resp = await authApi.loginMfa({ pre_auth_token: preAuthToken, code });
    applyAuthResponse(resp, setUser);
  }, []);

  const signup = useCallback(
    async (input: { company_name: string; email: string; password: string; full_name?: string }) => {
      const resp = await authApi.signup(input);
      applyAuthResponse(resp, setUser);
    },
    [],
  );

  const acceptInvite = useCallback(
    async (token: string, input: { password: string; full_name?: string }) => {
      const resp = await authApi.acceptInvite(token, input);
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
      // Marine threat model Scenario 1: destroy the offline vault DEK and any
      // cached jobs / pending actions so a lost-device logout leaves no
      // readable customer PII in IndexedDB on this profile.
      void wipeFieldOfflineData();
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, loginMfa, signup, acceptInvite, logout }),
    [user, loading, login, loginMfa, signup, acceptInvite, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}


