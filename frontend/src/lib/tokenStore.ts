// Session token storage.
//
// Access token: kept in memory only (a module-level variable), never
// persisted. It is short-lived (15 min server-side) and this avoids leaving
// it readable in localStorage/sessionStorage if the page is compromised via
// XSS.
//
// Refresh token: stored in localStorage. This is an accepted MVP shortcut,
// NOT a production-hardened choice — a refresh token readable by any script
// on the page is a real XSS blast-radius concern. The hardening item for
// later is moving refresh-token storage to an httpOnly, Secure, SameSite
// cookie set by the backend, which JS can never read. See README "Frontend"
// section, "Deferred", for tracking.
const REFRESH_TOKEN_KEY = "harboriq.refresh_token";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setRefreshToken(token: string | null): void {
  if (token) {
    localStorage.setItem(REFRESH_TOKEN_KEY, token);
  } else {
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  }
}

export function clearSession(): void {
  setAccessToken(null);
  setRefreshToken(null);
}
