// Session token storage.
//
// Access token: kept in memory only (a module-level variable), never
// persisted. It is short-lived (15 min server-side) and this avoids leaving
// it readable in localStorage/sessionStorage if the page is compromised via
// XSS.
//
// Refresh token: Phase 16 -- moved OFF the frontend entirely. The backend
// now sets it as an httpOnly, Secure (outside local dev), SameSite=Lax
// cookie (see `app/api/v1/routes/auth.py::_set_refresh_cookie`), which this
// module -- or any other JavaScript on the page -- can never read or write.
// There is deliberately no `getRefreshToken`/`setRefreshToken` here anymore;
// the browser attaches the cookie automatically on requests to the API
// origin with `credentials: "include"` (see `src/lib/api.ts`). The matching
// CSRF cookie (`csrf_token`) IS readable by design -- see
// `getCsrfToken` below and `app/core/csrf.py`'s docstring for why.
const CSRF_COOKIE_NAME = import.meta.env.VITE_CSRF_COOKIE_NAME ?? "csrf_token";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Reads the non-httpOnly double-submit CSRF cookie set alongside the
 * refresh-token cookie, so it can be echoed back as the `X-CSRF-Token`
 * header on `/auth/refresh`. Returns null if the cookie isn't set (no
 * session yet, or the cookie already expired). */
export function getCsrfToken(): string | null {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${CSRF_COOKIE_NAME}=`));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : null;
}

export function clearSession(): void {
  setAccessToken(null);
  // The httpOnly refresh cookie itself can only be cleared by the backend
  // (POST /auth/logout, or the server clearing it on a failed refresh) --
  // there is nothing for client JS to remove for that one.
}
