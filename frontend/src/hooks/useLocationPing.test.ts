import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { setAccessToken } from "../lib/tokenStore";
import { useLocationPing } from "./useLocationPing";
import type { User } from "../types/api";

const TECH: User = {
  id: "tech-1",
  company_id: "co-1",
  email: "tech@example.com",
  full_name: "Tech Person",
  role: "technician",
  is_active: true,
};

const OWNER: User = { ...TECH, role: "owner", id: "owner-1" };

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("useLocationPing", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("does nothing for a non-technician", () => {
    const getCurrentPosition = vi.fn();
    vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition } });

    const { result } = renderHook(() => useLocationPing(OWNER));

    expect(result.current.status).toBe("idle");
    expect(getCurrentPosition).not.toHaveBeenCalled();
  });

  it("reports 'unsupported' when the browser has no geolocation API", () => {
    vi.stubGlobal("navigator", { ...navigator, geolocation: undefined });

    const { result } = renderHook(() => useLocationPing(TECH));

    expect(result.current.status).toBe("unsupported");
  });

  it("pings the backend with the browser's coordinates for a technician", async () => {
    const getCurrentPosition = vi.fn((success: PositionCallback) => {
      success({
        coords: { latitude: 27.34, longitude: -82.54 },
      } as GeolocationPosition);
    });
    vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition } });

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "tech-1",
        current_latitude: "27.340000",
        current_longitude: "-82.540000",
        location_updated_at: "2026-08-04T12:00:00Z",
      }),
    );

    const { result } = renderHook(() => useLocationPing(TECH));

    await waitFor(() => expect(result.current.status).toBe("active"));

    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/users/me/location-ping");
    expect(JSON.parse(options.body)).toEqual({ latitude: "27.34", longitude: "-82.54" });
    expect(result.current.lastPingAt).not.toBeNull();
  });

  it("reports 'denied' when the user rejects the permission prompt", async () => {
    const getCurrentPosition = vi.fn((_success: PositionCallback, error: PositionErrorCallback) => {
      error({ code: 1, message: "denied" } as GeolocationPositionError);
    });
    vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition } });

    const { result } = renderHook(() => useLocationPing(TECH));

    await waitFor(() => expect(result.current.status).toBe("denied"));
  });
});
