import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { setAccessToken, setRefreshToken } from "../lib/tokenStore";
import { useFieldJobs } from "./useFieldJobs";
import { _resetForTests } from "../lib/offlineDb";
import type { Job } from "../types/api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const JOB_A: Job = {
  id: "job-a",
  company_id: "co-1",
  customer_id: "cust-1",
  vessel_id: null,
  title: "Replace impeller",
  description: null,
  status: "scheduled",
  priority: "normal",
  scheduled_at: "2026-08-05T14:00:00Z",
  scheduled_end_at: null,
  technician_id: "tech-1",
  started_at: null,
  completed_at: null,
  canceled_at: null,
  hold_reason: null,
  notes: null,
  required_skills: [],
  dispatch_score: null,
  dispatch_score_breakdown: null,
  dispatch_scored_at: null,
} as unknown as Job;

describe("useFieldJobs", () => {
  beforeEach(async () => {
    await _resetForTests();
    localStorage.clear();
    setAccessToken("access-token");
    setRefreshToken("refresh-token");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("loads jobs from the network and caches them to IndexedDB", async () => {
    const fetchMock = vi.fn(async () => jsonResponse([JOB_A]));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useFieldJobs());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.jobs).toEqual([JOB_A]);
    expect(result.current.fromCache).toBe(false);
    expect(result.current.error).toBeNull();
    expect(fetchMock).toHaveBeenCalled();
  });

  it("falls back to the last cached jobs and flags fromCache when the network fetch fails (offline)", async () => {
    // First render: succeeds and populates the cache.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse([JOB_A])),
    );
    const first = renderHook(() => useFieldJobs());
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    expect(first.result.current.jobs).toEqual([JOB_A]);
    first.unmount();

    // Second render: simulates going offline -- fetch rejects the way it
    // does in real browsers when there's no network connectivity at all.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const second = renderHook(() => useFieldJobs());
    await waitFor(() => expect(second.result.current.loading).toBe(false));

    expect(second.result.current.fromCache).toBe(true);
    expect(second.result.current.jobs).toEqual([JOB_A]);
    expect(second.result.current.error).toBeNull();
  });

  it("surfaces an error when offline with nothing cached yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const { result } = renderHook(() => useFieldJobs());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.jobs).toEqual([]);
    expect(result.current.fromCache).toBe(false);
    expect(result.current.error).toBeTruthy();
  });

  it("refresh() re-fetches and updates the cache", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([JOB_A]))
      .mockResolvedValueOnce(jsonResponse([{ ...JOB_A, title: "Updated title" }]));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useFieldJobs());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.jobs[0].title).toBe("Replace impeller");

    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.jobs[0].title).toBe("Updated title"));
  });
});
