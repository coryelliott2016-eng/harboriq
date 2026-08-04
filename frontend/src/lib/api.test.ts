import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Each test re-imports the module fresh (vi.resetModules) so the
// module-level `refreshInFlight` and token-store state never leak between
// cases.
async function freshApi() {
  vi.resetModules();
  return await import("./api");
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("api client 401-refresh-retry logic", () => {
  const assignMock = vi.fn();

  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
    assignMock.mockClear();
    // jsdom's window.location is non-configurable, so replace the whole
    // object with a stand-in that has a spyable `assign` (the forced-logout
    // redirect path calls `window.location.assign(...)`).
    vi.stubGlobal("location", { ...window.location, assign: assignMock });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("retries the original request once after a successful refresh", async () => {
    const { api } = await freshApi();
    const { setAccessToken, setRefreshToken } = await import("./tokenStore");
    setAccessToken("expired-token");
    setRefreshToken("valid-refresh-token");

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      // 1) the original request comes back 401
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid or expired token" }, 401))
      // 2) POST /auth/refresh succeeds
      .mockResolvedValueOnce(
        jsonResponse({
          user: { id: "u1", company_id: "c1", email: "a@b.com", full_name: null, role: "owner", is_active: true },
          tokens: { access_token: "new-token", refresh_token: "new-refresh", token_type: "bearer", expires_in: 900 },
        }),
      )
      // 3) the retried original request now succeeds
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    const result = await api.get("/auth/me");

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);

    // The retried call must carry the NEW access token, not the stale one.
    const thirdCallHeaders = fetchMock.mock.calls[2][1].headers;
    expect(thirdCallHeaders.Authorization).toBe("Bearer new-token");
  });

  it("clears the session and redirects to /login when refresh itself fails", async () => {
    const { api } = await freshApi();
    const { setAccessToken, setRefreshToken, getAccessToken, getRefreshToken } = await import(
      "./tokenStore"
    );
    setAccessToken("expired-token");
    setRefreshToken("stale-refresh-token");

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid or expired token" }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid refresh token" }, 401));

    await expect(api.get("/customers")).rejects.toThrow();

    expect(fetchMock).toHaveBeenCalledTimes(2); // original + one refresh attempt, no retry
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
    expect(assignMock).toHaveBeenCalledWith("/login");
  });

  it("does not attempt a refresh for anonymous (public) requests", async () => {
    const { apiRequest } = await freshApi();

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404));

    await expect(
      apiRequest("/public/invoice/bad-token", { anonymous: true }),
    ).rejects.toMatchObject({ status: 404 });

    // No refresh call should have been attempted.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not retry a second time if the retried request also 401s", async () => {
    const { api } = await freshApi();
    const { setAccessToken, setRefreshToken } = await import("./tokenStore");
    setAccessToken("expired-token");
    setRefreshToken("valid-refresh-token");

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid or expired token" }, 401))
      .mockResolvedValueOnce(
        jsonResponse({
          user: { id: "u1", company_id: "c1", email: "a@b.com", full_name: null, role: "owner", is_active: true },
          tokens: { access_token: "new-token", refresh_token: "new-refresh", token_type: "bearer", expires_in: 900 },
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid or expired token" }, 401));

    await expect(api.get("/auth/me")).rejects.toMatchObject({ status: 401 });

    // original (401) + refresh + retry (401) = 3 calls, then it gives up.
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
