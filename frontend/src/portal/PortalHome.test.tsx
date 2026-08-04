import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PortalHome } from "./PortalHome";

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
      <MemoryRouter initialEntries={[`/portal/${token}`]}>
        <Routes>
          <Route path="/portal/:token" element={<PortalHome />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortalHome", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the customer's profile and vessels once loaded", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "cust-1",
        first_name: "Jamie",
        last_name: "Halyard",
        company_name: null,
        email: "jamie@example.com",
        phone: "555-0100",
        vessels: [
          {
            id: "v1",
            name: "Sea Breeze",
            make: "Grady-White",
            model: "273",
            year: 2019,
            hull_id: null,
            registration: null,
          },
        ],
      }),
    );

    renderAtToken("good-token");

    expect(await screen.findByText(/Welcome, Jamie/)).toBeInTheDocument();
    expect(screen.getByText("jamie@example.com")).toBeInTheDocument();
    expect(screen.getByText("Sea Breeze")).toBeInTheDocument();

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/portal/good-token/me");
  });

  it("shows an invalid-link message on a 404", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404));

    renderAtToken("dead-token");

    expect(await screen.findByText(/invalid or has expired/)).toBeInTheDocument();
  });
});
