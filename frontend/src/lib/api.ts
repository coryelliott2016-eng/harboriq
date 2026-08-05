import type { ApiErrorBody, AuthResponse } from "../types/api";
import {
  clearSession,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from "./tokenStore";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const API_BASE = `${API_URL.replace(/\/$/, "")}/api/v1`;

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody | null;

  constructor(status: number, message: string, body: ApiErrorBody | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function extractErrorMessage(body: ApiErrorBody | null, fallback: string): string {
  if (!body || body.detail == null) return fallback;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => d.msg).join("; ") || fallback;
  }
  return fallback;
}

/** Redirect to /login, clearing whatever session state remains. Called only
 * when a refresh attempt has definitively failed. */
function forceLogout(): void {
  clearSession();
  if (window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

let refreshInFlight: Promise<boolean> | null = null;

/** Exchange the stored refresh token for a new pair. Returns true on success.
 * Concurrent callers share one in-flight refresh so a burst of 401s from
 * parallel requests does not each independently rotate the refresh token
 * (which would invalidate the others, per the backend's single-use
 * rotation). */
async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return false;
    try {
      const resp = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!resp.ok) return false;
      const data: AuthResponse = await resp.json();
      setAccessToken(data.tokens.access_token);
      setRefreshToken(data.tokens.refresh_token);
      return true;
    } catch {
      return false;
    }
  })();

  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Skip attaching the bearer token — used for public/unauthenticated routes. */
  anonymous?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${API_BASE}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function rawRequest<T>(path: string, options: RequestOptions): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (!options.anonymous) {
    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const resp = await fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (resp.status === 204) {
    return undefined as T;
  }

  const isJson = resp.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await resp.json().catch(() => null) : null;

  if (!resp.ok) {
    throw new ApiError(
      resp.status,
      extractErrorMessage(data, `Request failed with status ${resp.status}`),
      data,
    );
  }

  return data as T;
}

/**
 * Core request function used by every API call in the app.
 *
 * On a 401 from an authenticated (non-anonymous) request, attempts exactly
 * one `POST /auth/refresh` and retries the original request once. If the
 * refresh itself fails (expired/invalid refresh token), the session is
 * cleared and the browser is redirected to /login. This is the "401-refresh-
 * retry" logic covered by src/lib/api.test.ts.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await rawRequest<T>(path, options);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401 && !options.anonymous) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        return await rawRequest<T>(path, options);
      }
      forceLogout();
    }
    throw err;
  }
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"]) =>
    apiRequest<T>(path, { method: "GET", query }),
  post: <T>(path: string, body?: unknown, options?: Partial<RequestOptions>) =>
    apiRequest<T>(path, { method: "POST", body, ...options }),
  patch: <T>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => apiRequest<T>(path, { method: "DELETE" }),
};

// Exported for tests, which need to reset module-level refresh state between
// cases without re-importing the module.
export const __testing = { tryRefresh, forceLogout, rawRequest };

/**
 * Downloads a CSV (or other file) export from an authenticated GET endpoint
 * and saves it via the browser. Separate from `apiRequest` because CSV
 * export responses are `text/csv`, not `application/json` -- `rawRequest`
 * above only ever parses JSON bodies. Reuses the same 401-refresh-retry
 * policy as `apiRequest` so an expired access token doesn't silently
 * download an error page as a "csv".
 */
export async function downloadFile(
  path: string,
  query?: RequestOptions["query"],
  suggestedFilename?: string,
): Promise<void> {
  const doFetch = async (): Promise<Response> => {
    const token = getAccessToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(buildUrl(path, query), { method: "GET", headers });
  };

  let resp = await doFetch();
  if (resp.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      resp = await doFetch();
    } else {
      forceLogout();
      throw new ApiError(401, "Session expired.", null);
    }
  }

  if (!resp.ok) {
    let data: ApiErrorBody | null = null;
    try {
      data = await resp.json();
    } catch {
      // ignore -- not a JSON error body
    }
    throw new ApiError(resp.status, extractErrorMessage(data, `Request failed with status ${resp.status}`), data);
  }

  const blob = await resp.blob();
  const disposition = resp.headers.get("content-disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const filename = match?.[1] ?? suggestedFilename ?? "export.csv";

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
