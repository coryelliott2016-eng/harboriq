import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken, setRefreshToken } from "./tokenStore";
import { dispatchApi, jobsApi } from "./services";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("dispatch API client", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken("access-token");
    setRefreshToken("refresh-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fetches ranked candidates for a job", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          technician_id: "tech-1",
          technician_name: "Alex Rivera",
          score: { total: "42.50", breakdown: { urgency: "17.50" } },
        },
      ]),
    );

    const candidates = await dispatchApi.candidates("job-1");

    expect(candidates).toHaveLength(1);
    expect(candidates[0].technician_name).toBe("Alex Rivera");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/jobs/job-1/dispatch/candidates");
  });

  it("posts to recompute and returns the cached score", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        job_id: "job-1",
        dispatch_score: "30.00",
        dispatch_score_breakdown: { urgency: "17.50" },
        dispatch_scored_at: null,
      }),
    );

    const result = await dispatchApi.recompute("job-1");

    expect(result.dispatch_score).toBe("30.00");
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/jobs/job-1/dispatch/recompute");
    expect(options.method).toBe("POST");
  });

  it("passes sort=priority_score through to GET /jobs", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    await jobsApi.list({ sort: "priority_score" });

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("sort=priority_score");
  });
});
