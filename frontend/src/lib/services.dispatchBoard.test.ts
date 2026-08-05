import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken } from "./tokenStore";
import { jobsApi, usersApi } from "./services";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("Phase 11 dispatch board API client", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("posts a location ping to /users/me/location-ping", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "user-1",
        current_latitude: "27.340000",
        current_longitude: "-82.540000",
        location_updated_at: "2026-08-04T12:00:00Z",
      }),
    );

    const result = await usersApi.pingLocation({ latitude: "27.34", longitude: "-82.54" });

    expect(result.current_latitude).toBe("27.340000");
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/users/me/location-ping");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ latitude: "27.34", longitude: "-82.54" });
  });

  it("fetches technician locations", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: "tech-1",
          full_name: "Alex Rivera",
          latitude: "27.340000",
          longitude: "-82.540000",
          is_live: true,
          location_updated_at: "2026-08-04T12:00:00Z",
        },
      ]),
    );

    const locations = await usersApi.technicianLocations();

    expect(locations).toHaveLength(1);
    expect(locations[0].is_live).toBe(true);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/users/technician-locations");
  });

  it("posts to notify-on-my-way for a job", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ outbox_event_id: 42 }));

    const result = await jobsApi.notifyOnMyWay("job-1");

    expect(result.outbox_event_id).toBe(42);
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/jobs/job-1/notify-on-my-way");
    expect(options.method).toBe("POST");
  });

  it("assign still posts technician_id to /jobs/{id}/assign (unchanged mechanism)", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "job-1" }));

    await jobsApi.assign("job-1", "tech-1");

    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/jobs/job-1/assign");
    expect(JSON.parse(options.body)).toEqual({ technician_id: "tech-1" });
  });
});
