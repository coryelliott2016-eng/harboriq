import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PortalDockLocation } from "./PortalDockLocation";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderAtToken(token: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/portal/${token}/dock`]}>
        <Routes>
          <Route path="/portal/:token/dock" element={<PortalDockLocation />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortalDockLocation", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders a map with the customer's own slip location", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          reservation_id: "res-1",
          status: "confirmed",
          start_date: "2026-01-01",
          end_date: "2026-12-31",
          slip_id: "slip-1",
          slip_identifier: "A-12",
          latitude: "27.3367",
          longitude: "-82.5307",
        },
      ]),
    );

    renderAtToken("good-token");

    expect(await screen.findByText("Slip A-12")).toBeInTheDocument();
    expect(await screen.findByTestId("dock-location-map")).toBeInTheDocument();
    expect(screen.getByText("confirmed")).toBeInTheDocument();

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/portal/good-token/dock-locations");
  });

  it("shows an empty state when no GPS location is on file", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    renderAtToken("good-token");

    expect(await screen.findByText(/No GPS location on file/)).toBeInTheDocument();
  });

  it("shows an invalid-link message on a 404", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404));

    renderAtToken("dead-token");

    expect(await screen.findByText(/invalid or has expired/)).toBeInTheDocument();
  });
});
